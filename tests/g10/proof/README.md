# G10 A1 proof roots

Every root must verify in default and infer modes, then reach the G10 code-generation
guard on both backends. The runner group is g10_proof; g10_v_* rejection roots run
in must_reject with the existing verify/call_requires or verify/assert diagnostic.

checksum.pruv follows G10_SPEC 2.3 with an explicit ensures result >= 0 on
sum_bytes. The printed specification omits this summary: modular verification
cannot otherwise establish checksum's result >= -1 at the call to sum_bytes.

The frontend write_close fixture checks file_writable again after file_write_str:
each filesystem result is fresh and the write may fail.
