// Self-contained copy of the base64 0.22.1 general-purpose engine (STANDARD alphabet, padding on, canonical padding
// required, trailing bits rejected) as used by the kostya driver (reference.rs). Encode path: internal_encode
// (4x unrolled big-endian u64 fast loop, 3-byte tail loop, 1-2 byte remainder) + add_padding. Decode path:
// decode_helper (32-byte unrolled u64 chunks, 4-byte chunks) + decode_suffix (u32 shifts). Copied from
// upstream/general_purpose_mod.rs, upstream/decode.rs, upstream/decode_suffix.rs and the crate's Engine::encode /
// Engine::decode wrappers; error types are reduced to what the code paths need.
// Not copied: the String::from_utf8 validation of Engine::encode (output stays a Vec<u8>).
//
// bench(data, n): input = 131072 bytes b'a' built here, n = TRIES. One encode first (the driver's `output`), then
// n encodes (summing encoded lengths), then n decodes of that text (summing decoded lengths).
// Result: [sum_encoded, sum_decoded, checksum]; checksum = sum of the bytes of the last encoded buffer plus the sum of
// the bytes of the last decoded buffer.

use std::convert::TryInto;

const STR_SIZE: usize = 131_072;
const INVALID_VALUE: u8 = 255;
const PAD_BYTE: u8 = b'=';
const STANDARD_SYMBOLS: [u8; 64] = *b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

#[derive(Debug, Clone, PartialEq, Eq)]
enum DecodeError {
    InvalidByte(usize, u8),
    InvalidLength(usize),
    InvalidLastSymbol(usize, u8),
    InvalidPadding,
}

#[derive(Debug)]
enum DecodeSliceError {
    DecodeError(DecodeError),
    OutputSliceTooSmall,
}

impl From<DecodeError> for DecodeSliceError {
    fn from(e: DecodeError) -> Self {
        DecodeSliceError::DecodeError(e)
    }
}

#[derive(Clone, Copy, Debug)]
enum DecodePaddingMode {
    Indifferent,
    RequireCanonical,
    RequireNone,
}

struct DecodeMetadata {
    decoded_len: usize,
    padding_offset: Option<usize>,
}

impl DecodeMetadata {
    fn new(decoded_len: usize, padding_offset: Option<usize>) -> Self {
        Self { decoded_len, padding_offset }
    }
}

#[derive(Clone, Copy, Debug)]
struct GeneralPurposeConfig {
    encode_padding: bool,
    decode_allow_trailing_bits: bool,
    decode_padding_mode: DecodePaddingMode,
}

const PAD: GeneralPurposeConfig = GeneralPurposeConfig {
    encode_padding: true,
    decode_allow_trailing_bits: false,
    decode_padding_mode: DecodePaddingMode::RequireCanonical,
};

#[derive(Debug, Clone)]
struct GeneralPurpose {
    encode_table: [u8; 64],
    decode_table: [u8; 256],
    config: GeneralPurposeConfig,
}

const STANDARD: GeneralPurpose = GeneralPurpose::new(&STANDARD_SYMBOLS, PAD);

const fn encode_table(symbols: &[u8; 64]) -> [u8; 64] {
    let mut encode_table = [0_u8; 64];
    {
        let mut index = 0;
        while index < 64 {
            encode_table[index] = symbols[index];
            index += 1;
        }
    }
    encode_table
}

const fn decode_table(symbols: &[u8; 64]) -> [u8; 256] {
    let mut decode_table = [INVALID_VALUE; 256];
    let mut index = 0;
    while index < 64 {
        decode_table[symbols[index] as usize] = index as u8;
        index += 1;
    }
    decode_table
}

#[inline]
fn read_u64(s: &[u8]) -> u64 {
    u64::from_be_bytes(s[..8].try_into().unwrap())
}

struct GeneralPurposeEstimate {
    /// input len % 4
    rem: usize,
    conservative_decoded_len: usize,
}

impl GeneralPurposeEstimate {
    fn new(encoded_len: usize) -> Self {
        let rem = encoded_len % 4;
        Self {
            rem,
            conservative_decoded_len: (encoded_len / 4 + (rem > 0) as usize) * 3,
        }
    }

    fn decoded_len_estimate(&self) -> usize {
        self.conservative_decoded_len
    }
}

impl GeneralPurpose {
    const fn new(symbols: &[u8; 64], config: GeneralPurposeConfig) -> Self {
        Self {
            encode_table: encode_table(symbols),
            decode_table: decode_table(symbols),
            config,
        }
    }

    // Engine::encode wrapper of the crate (without the final String::from_utf8).
    fn encode(&self, input: &[u8]) -> Vec<u8> {
        let encoded_size = encoded_len(input.len(), self.config.encode_padding)
            .expect("integer overflow when calculating buffer size");
        let mut buf = vec![0; encoded_size];

        let b64_bytes_written = self.internal_encode(input, &mut buf[..]);
        let padding_bytes = if self.config.encode_padding {
            add_padding(b64_bytes_written, &mut buf[b64_bytes_written..])
        } else {
            0
        };
        let encoded_bytes = b64_bytes_written
            .checked_add(padding_bytes)
            .expect("usize overflow when calculating b64 length");
        debug_assert_eq!(encoded_size, encoded_bytes);
        buf
    }

    // Engine::decode wrapper of the crate.
    fn decode(&self, input: &[u8]) -> Result<Vec<u8>, DecodeError> {
        let estimate = GeneralPurposeEstimate::new(input.len());
        let mut buffer = vec![0; estimate.decoded_len_estimate()];

        let bytes_written = self
            .internal_decode(input, &mut buffer, estimate)
            .map_err(|e| match e {
                DecodeSliceError::DecodeError(e) => e,
                DecodeSliceError::OutputSliceTooSmall => {
                    unreachable!("Vec is sized conservatively")
                }
            })?
            .decoded_len;

        buffer.truncate(bytes_written);

        Ok(buffer)
    }

    fn internal_encode(&self, input: &[u8], output: &mut [u8]) -> usize {
        let mut input_index: usize = 0;

        const BLOCKS_PER_FAST_LOOP: usize = 4;
        const LOW_SIX_BITS: u64 = 0x3F;

        // we read 8 bytes at a time (u64) but only actually consume 6 of those bytes. Thus, we need
        // 2 trailing bytes to be available to read..
        let last_fast_index = input.len().saturating_sub(BLOCKS_PER_FAST_LOOP * 6 + 2);
        let mut output_index = 0;

        if last_fast_index > 0 {
            while input_index <= last_fast_index {
                // Major performance wins from letting the optimizer do the bounds check once, mostly
                // on the output side
                let input_chunk =
                    &input[input_index..(input_index + (BLOCKS_PER_FAST_LOOP * 6 + 2))];
                let output_chunk =
                    &mut output[output_index..(output_index + BLOCKS_PER_FAST_LOOP * 8)];

                let input_u64 = read_u64(&input_chunk[0..]);

                output_chunk[0] = self.encode_table[((input_u64 >> 58) & LOW_SIX_BITS) as usize];
                output_chunk[1] = self.encode_table[((input_u64 >> 52) & LOW_SIX_BITS) as usize];
                output_chunk[2] = self.encode_table[((input_u64 >> 46) & LOW_SIX_BITS) as usize];
                output_chunk[3] = self.encode_table[((input_u64 >> 40) & LOW_SIX_BITS) as usize];
                output_chunk[4] = self.encode_table[((input_u64 >> 34) & LOW_SIX_BITS) as usize];
                output_chunk[5] = self.encode_table[((input_u64 >> 28) & LOW_SIX_BITS) as usize];
                output_chunk[6] = self.encode_table[((input_u64 >> 22) & LOW_SIX_BITS) as usize];
                output_chunk[7] = self.encode_table[((input_u64 >> 16) & LOW_SIX_BITS) as usize];

                let input_u64 = read_u64(&input_chunk[6..]);

                output_chunk[8] = self.encode_table[((input_u64 >> 58) & LOW_SIX_BITS) as usize];
                output_chunk[9] = self.encode_table[((input_u64 >> 52) & LOW_SIX_BITS) as usize];
                output_chunk[10] = self.encode_table[((input_u64 >> 46) & LOW_SIX_BITS) as usize];
                output_chunk[11] = self.encode_table[((input_u64 >> 40) & LOW_SIX_BITS) as usize];
                output_chunk[12] = self.encode_table[((input_u64 >> 34) & LOW_SIX_BITS) as usize];
                output_chunk[13] = self.encode_table[((input_u64 >> 28) & LOW_SIX_BITS) as usize];
                output_chunk[14] = self.encode_table[((input_u64 >> 22) & LOW_SIX_BITS) as usize];
                output_chunk[15] = self.encode_table[((input_u64 >> 16) & LOW_SIX_BITS) as usize];

                let input_u64 = read_u64(&input_chunk[12..]);

                output_chunk[16] = self.encode_table[((input_u64 >> 58) & LOW_SIX_BITS) as usize];
                output_chunk[17] = self.encode_table[((input_u64 >> 52) & LOW_SIX_BITS) as usize];
                output_chunk[18] = self.encode_table[((input_u64 >> 46) & LOW_SIX_BITS) as usize];
                output_chunk[19] = self.encode_table[((input_u64 >> 40) & LOW_SIX_BITS) as usize];
                output_chunk[20] = self.encode_table[((input_u64 >> 34) & LOW_SIX_BITS) as usize];
                output_chunk[21] = self.encode_table[((input_u64 >> 28) & LOW_SIX_BITS) as usize];
                output_chunk[22] = self.encode_table[((input_u64 >> 22) & LOW_SIX_BITS) as usize];
                output_chunk[23] = self.encode_table[((input_u64 >> 16) & LOW_SIX_BITS) as usize];

                let input_u64 = read_u64(&input_chunk[18..]);

                output_chunk[24] = self.encode_table[((input_u64 >> 58) & LOW_SIX_BITS) as usize];
                output_chunk[25] = self.encode_table[((input_u64 >> 52) & LOW_SIX_BITS) as usize];
                output_chunk[26] = self.encode_table[((input_u64 >> 46) & LOW_SIX_BITS) as usize];
                output_chunk[27] = self.encode_table[((input_u64 >> 40) & LOW_SIX_BITS) as usize];
                output_chunk[28] = self.encode_table[((input_u64 >> 34) & LOW_SIX_BITS) as usize];
                output_chunk[29] = self.encode_table[((input_u64 >> 28) & LOW_SIX_BITS) as usize];
                output_chunk[30] = self.encode_table[((input_u64 >> 22) & LOW_SIX_BITS) as usize];
                output_chunk[31] = self.encode_table[((input_u64 >> 16) & LOW_SIX_BITS) as usize];

                output_index += BLOCKS_PER_FAST_LOOP * 8;
                input_index += BLOCKS_PER_FAST_LOOP * 6;
            }
        }

        // Encode what's left after the fast loop.

        const LOW_SIX_BITS_U8: u8 = 0x3F;

        let rem = input.len() % 3;
        let start_of_rem = input.len() - rem;

        // start at the first index not handled by fast loop, which may be 0.

        while input_index < start_of_rem {
            let input_chunk = &input[input_index..(input_index + 3)];
            let output_chunk = &mut output[output_index..(output_index + 4)];

            output_chunk[0] = self.encode_table[(input_chunk[0] >> 2) as usize];
            output_chunk[1] = self.encode_table
                [((input_chunk[0] << 4 | input_chunk[1] >> 4) & LOW_SIX_BITS_U8) as usize];
            output_chunk[2] = self.encode_table
                [((input_chunk[1] << 2 | input_chunk[2] >> 6) & LOW_SIX_BITS_U8) as usize];
            output_chunk[3] = self.encode_table[(input_chunk[2] & LOW_SIX_BITS_U8) as usize];

            input_index += 3;
            output_index += 4;
        }

        if rem == 2 {
            output[output_index] = self.encode_table[(input[start_of_rem] >> 2) as usize];
            output[output_index + 1] =
                self.encode_table[((input[start_of_rem] << 4 | input[start_of_rem + 1] >> 4)
                    & LOW_SIX_BITS_U8) as usize];
            output[output_index + 2] =
                self.encode_table[((input[start_of_rem + 1] << 2) & LOW_SIX_BITS_U8) as usize];
            output_index += 3;
        } else if rem == 1 {
            output[output_index] = self.encode_table[(input[start_of_rem] >> 2) as usize];
            output[output_index + 1] =
                self.encode_table[((input[start_of_rem] << 4) & LOW_SIX_BITS_U8) as usize];
            output_index += 2;
        }

        output_index
    }

    fn internal_decode(
        &self,
        input: &[u8],
        output: &mut [u8],
        estimate: GeneralPurposeEstimate,
    ) -> Result<DecodeMetadata, DecodeSliceError> {
        decode_helper(
            input,
            estimate,
            output,
            &self.decode_table,
            self.config.decode_allow_trailing_bits,
            self.config.decode_padding_mode,
        )
    }
}

// base64::encoded_len for the padded case.
fn encoded_len(bytes_len: usize, padding: bool) -> Option<usize> {
    let rem = bytes_len % 3;

    let complete_input_chunks = bytes_len / 3;
    let complete_chunk_output = complete_input_chunks.checked_mul(4)?;

    if rem > 0 {
        if padding {
            complete_chunk_output.checked_add(4)
        } else {
            let encoded_rem = if rem == 1 { 2 } else { 3 };
            complete_chunk_output.checked_add(encoded_rem)
        }
    } else {
        Some(complete_chunk_output)
    }
}

fn add_padding(unpadded_output_len: usize, output: &mut [u8]) -> usize {
    let pad_bytes = (4 - (unpadded_output_len % 4)) % 4;
    // for just a couple bytes, this has better performance than using
    // .fill(), or iterating over mutable refs, which call memset()
    #[allow(clippy::needless_range_loop)]
    for i in 0..pad_bytes {
        output[i] = PAD_BYTE;
    }

    pad_bytes
}

#[inline]
fn decode_helper(
    input: &[u8],
    estimate: GeneralPurposeEstimate,
    output: &mut [u8],
    decode_table: &[u8; 256],
    decode_allow_trailing_bits: bool,
    padding_mode: DecodePaddingMode,
) -> Result<DecodeMetadata, DecodeSliceError> {
    let input_complete_nonterminal_quads_len =
        complete_quads_len(input, estimate.rem, output.len(), decode_table)?;

    const UNROLLED_INPUT_CHUNK_SIZE: usize = 32;
    const UNROLLED_OUTPUT_CHUNK_SIZE: usize = UNROLLED_INPUT_CHUNK_SIZE / 4 * 3;

    let input_complete_quads_after_unrolled_chunks_len =
        input_complete_nonterminal_quads_len % UNROLLED_INPUT_CHUNK_SIZE;

    let input_unrolled_loop_len =
        input_complete_nonterminal_quads_len - input_complete_quads_after_unrolled_chunks_len;

    // chunks of 32 bytes
    for (chunk_index, chunk) in input[..input_unrolled_loop_len]
        .chunks_exact(UNROLLED_INPUT_CHUNK_SIZE)
        .enumerate()
    {
        let input_index = chunk_index * UNROLLED_INPUT_CHUNK_SIZE;
        let chunk_output = &mut output[chunk_index * UNROLLED_OUTPUT_CHUNK_SIZE
            ..(chunk_index + 1) * UNROLLED_OUTPUT_CHUNK_SIZE];

        decode_chunk_8(
            &chunk[0..8],
            input_index,
            decode_table,
            &mut chunk_output[0..6],
        )?;
        decode_chunk_8(
            &chunk[8..16],
            input_index + 8,
            decode_table,
            &mut chunk_output[6..12],
        )?;
        decode_chunk_8(
            &chunk[16..24],
            input_index + 16,
            decode_table,
            &mut chunk_output[12..18],
        )?;
        decode_chunk_8(
            &chunk[24..32],
            input_index + 24,
            decode_table,
            &mut chunk_output[18..24],
        )?;
    }

    // remaining quads, except for the last possibly partial one, as it may have padding
    let output_unrolled_loop_len = input_unrolled_loop_len / 4 * 3;
    let output_complete_quad_len = input_complete_nonterminal_quads_len / 4 * 3;
    {
        let output_after_unroll = &mut output[output_unrolled_loop_len..output_complete_quad_len];

        for (chunk_index, chunk) in input
            [input_unrolled_loop_len..input_complete_nonterminal_quads_len]
            .chunks_exact(4)
            .enumerate()
        {
            let chunk_output = &mut output_after_unroll[chunk_index * 3..chunk_index * 3 + 3];

            decode_chunk_4(
                chunk,
                input_unrolled_loop_len + chunk_index * 4,
                decode_table,
                chunk_output,
            )?;
        }
    }

    decode_suffix(
        input,
        input_complete_nonterminal_quads_len,
        output,
        output_complete_quad_len,
        decode_table,
        decode_allow_trailing_bits,
        padding_mode,
    )
}

fn complete_quads_len(
    input: &[u8],
    input_len_rem: usize,
    output_len: usize,
    decode_table: &[u8; 256],
) -> Result<usize, DecodeSliceError> {
    debug_assert!(input.len() % 4 == input_len_rem);

    // detect a trailing invalid byte, like a newline, as a user convenience
    if input_len_rem == 1 {
        let last_byte = input[input.len() - 1];
        // exclude pad bytes; might be part of padding that extends from earlier in the input
        if last_byte != PAD_BYTE && decode_table[usize::from(last_byte)] == INVALID_VALUE {
            return Err(DecodeError::InvalidByte(input.len() - 1, last_byte).into());
        }
    };

    // skip last quad, even if it's complete, as it may have padding
    let input_complete_nonterminal_quads_len = input
        .len()
        .saturating_sub(input_len_rem)
        // if rem was 0, subtract 4 to avoid padding
        .saturating_sub((input_len_rem == 0) as usize * 4);
    debug_assert!(
        input.is_empty() || (1..=4).contains(&(input.len() - input_complete_nonterminal_quads_len))
    );

    // check that everything except the last quad handled by decode_suffix will fit
    if output_len < input_complete_nonterminal_quads_len / 4 * 3 {
        return Err(DecodeSliceError::OutputSliceTooSmall);
    };
    Ok(input_complete_nonterminal_quads_len)
}

#[inline(always)]
fn decode_chunk_8(
    input: &[u8],
    index_at_start_of_input: usize,
    decode_table: &[u8; 256],
    output: &mut [u8],
) -> Result<(), DecodeError> {
    let morsel = decode_table[usize::from(input[0])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(index_at_start_of_input, input[0]));
    }
    let mut accum = u64::from(morsel) << 58;

    let morsel = decode_table[usize::from(input[1])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 1,
            input[1],
        ));
    }
    accum |= u64::from(morsel) << 52;

    let morsel = decode_table[usize::from(input[2])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 2,
            input[2],
        ));
    }
    accum |= u64::from(morsel) << 46;

    let morsel = decode_table[usize::from(input[3])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 3,
            input[3],
        ));
    }
    accum |= u64::from(morsel) << 40;

    let morsel = decode_table[usize::from(input[4])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 4,
            input[4],
        ));
    }
    accum |= u64::from(morsel) << 34;

    let morsel = decode_table[usize::from(input[5])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 5,
            input[5],
        ));
    }
    accum |= u64::from(morsel) << 28;

    let morsel = decode_table[usize::from(input[6])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 6,
            input[6],
        ));
    }
    accum |= u64::from(morsel) << 22;

    let morsel = decode_table[usize::from(input[7])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 7,
            input[7],
        ));
    }
    accum |= u64::from(morsel) << 16;

    output[..6].copy_from_slice(&accum.to_be_bytes()[..6]);

    Ok(())
}

#[inline(always)]
fn decode_chunk_4(
    input: &[u8],
    index_at_start_of_input: usize,
    decode_table: &[u8; 256],
    output: &mut [u8],
) -> Result<(), DecodeError> {
    let morsel = decode_table[usize::from(input[0])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(index_at_start_of_input, input[0]));
    }
    let mut accum = u32::from(morsel) << 26;

    let morsel = decode_table[usize::from(input[1])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 1,
            input[1],
        ));
    }
    accum |= u32::from(morsel) << 20;

    let morsel = decode_table[usize::from(input[2])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 2,
            input[2],
        ));
    }
    accum |= u32::from(morsel) << 14;

    let morsel = decode_table[usize::from(input[3])];
    if morsel == INVALID_VALUE {
        return Err(DecodeError::InvalidByte(
            index_at_start_of_input + 3,
            input[3],
        ));
    }
    accum |= u32::from(morsel) << 8;

    output[..3].copy_from_slice(&accum.to_be_bytes()[..3]);

    Ok(())
}

fn decode_suffix(
    input: &[u8],
    input_index: usize,
    output: &mut [u8],
    mut output_index: usize,
    decode_table: &[u8; 256],
    decode_allow_trailing_bits: bool,
    padding_mode: DecodePaddingMode,
) -> Result<DecodeMetadata, DecodeSliceError> {
    debug_assert!((input.len() - input_index) <= 4);

    // Decode any leftovers that might not be a complete input chunk of 4 bytes.
    // Use a u32 as a stack-resident 4 byte buffer.
    let mut morsels_in_leftover = 0;
    let mut padding_bytes_count = 0;
    // offset from input_index
    let mut first_padding_offset: usize = 0;
    let mut last_symbol = 0_u8;
    let mut morsels = [0_u8; 4];

    for (leftover_index, &b) in input[input_index..].iter().enumerate() {
        // '=' padding
        if b == PAD_BYTE {
            if leftover_index < 2 {
                debug_assert!(
                    leftover_index == 0 || (leftover_index == 1 && padding_bytes_count == 0)
                );
                let bad_padding_index = input_index + leftover_index;
                return Err(DecodeError::InvalidByte(bad_padding_index, b).into());
            }

            if padding_bytes_count == 0 {
                first_padding_offset = leftover_index;
            }

            padding_bytes_count += 1;
            continue;
        }

        // Check for case #1.
        // To make '=' handling consistent with the main loop, don't allow
        // non-suffix '=' in trailing chunk either. Report error as first
        // erroneous padding.
        if padding_bytes_count > 0 {
            return Err(
                DecodeError::InvalidByte(input_index + first_padding_offset, PAD_BYTE).into(),
            );
        }

        last_symbol = b;

        // can use up to 8 * 6 = 48 bits of the u64, if last chunk has no padding.
        // Pack the leftovers from left to right.
        let morsel = decode_table[b as usize];
        if morsel == INVALID_VALUE {
            return Err(DecodeError::InvalidByte(input_index + leftover_index, b).into());
        }

        morsels[morsels_in_leftover] = morsel;
        morsels_in_leftover += 1;
    }

    // If there was 1 trailing byte, and it was valid, and we got to this point without hitting
    // an invalid byte, now we can report invalid length
    if !input.is_empty() && morsels_in_leftover < 2 {
        return Err(DecodeError::InvalidLength(input_index + morsels_in_leftover).into());
    }

    match padding_mode {
        DecodePaddingMode::Indifferent => { /* everything we care about was already checked */ }
        DecodePaddingMode::RequireCanonical => {
            // allow empty input
            if (padding_bytes_count + morsels_in_leftover) % 4 != 0 {
                return Err(DecodeError::InvalidPadding.into());
            }
        }
        DecodePaddingMode::RequireNone => {
            if padding_bytes_count > 0 {
                // check at the end to make sure we let the cases of padding that should be InvalidByte
                // get hit
                return Err(DecodeError::InvalidPadding.into());
            }
        }
    }

    let leftover_bytes_to_append = morsels_in_leftover * 6 / 8;
    // Put the up to 6 complete bytes as the high bytes.
    // Gain a couple percent speedup from nudging these ORs to use more ILP with a two-way split.
    let mut leftover_num = (u32::from(morsels[0]) << 26)
        | (u32::from(morsels[1]) << 20)
        | (u32::from(morsels[2]) << 14)
        | (u32::from(morsels[3]) << 8);

    // if there are bits set outside the bits we care about, last symbol encodes trailing bits that
    // will not be included in the output
    let mask = !0_u32 >> (leftover_bytes_to_append * 8);
    if !decode_allow_trailing_bits && (leftover_num & mask) != 0 {
        // last morsel is at `morsels_in_leftover` - 1
        return Err(DecodeError::InvalidLastSymbol(
            input_index + morsels_in_leftover - 1,
            last_symbol,
        )
        .into());
    }

    // Strangely, this approach benchmarks better than writing bytes one at a time,
    // or copy_from_slice into output.
    for _ in 0..leftover_bytes_to_append {
        let hi_byte = (leftover_num >> 24) as u8;
        leftover_num <<= 8;
        *output
            .get_mut(output_index)
            .ok_or(DecodeSliceError::OutputSliceTooSmall)? = hi_byte;
        output_index += 1;
    }

    Ok(DecodeMetadata::new(
        output_index,
        if padding_bytes_count > 0 {
            Some(input_index + first_padding_offset)
        } else {
            None
        },
    ))
}

pub fn bench(_data: &[u8], n: i64) -> Vec<i64> {
    let engine = STANDARD;
    let input = vec![b'a'; STR_SIZE];
    let output = engine.encode(&input);
    let tries = n as usize;

    let mut sum_encoded: usize = 0;
    let mut last_encoded: Vec<u8> = Vec::new();
    for _ in 0..tries {
        last_encoded = engine.encode(&input);
        sum_encoded += last_encoded.len();
    }

    let mut sum_decoded: usize = 0;
    let mut last_decoded: Vec<u8> = Vec::new();
    for _ in 0..tries {
        last_decoded = engine.decode(&output).unwrap();
        sum_decoded += last_decoded.len();
    }

    let checksum: i64 = last_encoded.iter().map(|&b| b as i64).sum::<i64>()
        + last_decoded.iter().map(|&b| b as i64).sum::<i64>();
    vec![sum_encoded as i64, sum_decoded as i64, checksum]
}
