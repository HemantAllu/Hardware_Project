#!/usr/bin/env python3
"""bin2hex.py <in.bin> <out.hex> [words]  - little-endian 32-bit words, one hex word per line."""
import sys

src, dst = sys.argv[1], sys.argv[2]
words = int(sys.argv[3]) if len(sys.argv) > 3 else 0
data = open(src, 'rb').read() if src != '-' else b''
data += b'\x00' * ((-len(data)) % 4)
out = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
if words:
    out += [0] * (words - len(out))
with open(dst, 'w') as f:
    for w in out:
        f.write(f"{w:08x}\n")
