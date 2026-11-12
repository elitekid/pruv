# G10 file problems

Use default verification. Each project has `qNN/root.pruv`. Paths are host `str` values;
no File crosses the host boundary. The grader fixes the following public headers.
Other helpers and modules are permitted. File system contents are checked at runtime:
G10 does not prove relationships between separate opens.

## q01 — photographic byte negative

```
pub fn transform(input: str, output: str) -> i64 ! fs, alloc
  ensures -3 <= result && result <= 0
```

Read the entire input before creating/truncating output. Replace every byte b with 255-b,
in order, without interpreting UTF-8. Return 0 only after writing and explicitly closing
the output successfully; -1 if opening/reading input fails; -3 if the successfully read
input exceeds 10,000,000 bytes; -2 if creating/writing/closing output fails. Input errors
take priority and leave output unchanged. Equal input/output paths are supported.
No guarantee is made about output contents after an output failure.

Python reference (OSError on close is included):

```python
def transform(input, output):
    try:
        with open(input, 'rb') as f:
            data = f.read()
    except OSError:
        return -1
    if len(data) > 10_000_000:
        return -3
    try:
        with open(output, 'wb') as f:
            f.write(bytes(255 - b for b in data))
    except OSError:
        return -2
    return 0
```

Cases: empty -> empty; [0,127,255] -> [255,128,0]; all 256 byte values;
embedded NUL and invalid UTF-8; existing longer output must be truncated; missing input
preserves existing output; directory output and nonexistent parent -> -2; 10,000,001
bytes -> -3; same path -> transformed bytes. The grader also uses seeded random bytes.

## q02 — unquoted byte-delimited records

```
pub fn count_fields(path: str) -> i64 ! fs, alloc
  ensures -2 <= result && result <= 4097 * 10001
```

Missing/unreadable input returns -1; successful reads over 4096 bytes return -2.
Empty input has zero lines and fields. Every LF (byte 10) terminates a line, including
an empty line; a nonempty suffix without LF is another line. A trailing LF adds no
extra line. Each line has one field plus its number of commas (byte 44); empty fields
count. Quotes and CR have no special meaning. Return 10000*lines + fields.

```python
def count_fields(path):
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return -1
    if len(data) > 4096:
        return -2
    lines = data.count(b'\n') + int(bool(data) and not data.endswith(b'\n'))
    fields = lines + data.count(b',')
    return 10000 * lines + fields
```

Cases: empty -> 0; `a,b\n` -> 10002; `\n` -> 10001; `,` -> 10002;
`,,\n\n` -> 20004; `a\r\nb,c` -> 20003; 4096 commas -> 14097;
4096 LF -> 40964096; 4097 bytes -> -2; missing path -> -1. Arbitrary binary
bytes other than LF/comma are ordinary field contents.
