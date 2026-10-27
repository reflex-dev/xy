//! Stable animation identity encoding.
//!
//! The public Python API accepts several scalar key types and defines their
//! identity through a short, type-qualified byte token.  This module reproduces
//! those tokens directly from homogeneous NumPy fixed-width storage, hashes
//! them with the same personalized eight-byte BLAKE2s digest, and checks
//! uniqueness without materializing one Python object per row.

use std::collections::HashMap;

pub const KIND_UNICODE: u32 = 0;
pub const KIND_BYTES: u32 = 1;
pub const KIND_BOOL: u32 = 2;
pub const KIND_SIGNED: u32 = 3;
pub const KIND_UNSIGNED: u32 = 4;
pub const KIND_FLOAT64: u32 = 5;

#[derive(Debug, PartialEq, Eq)]
pub enum TransitionKeyError {
    Invalid { index: Option<usize> },
    Duplicate { first: usize, index: usize },
    Collision { first: usize, index: usize },
}

const BLAKE2S_IV: [u32; 8] = [
    0x6A09_E667,
    0xBB67_AE85,
    0x3C6E_F372,
    0xA54F_F53A,
    0x510E_527F,
    0x9B05_688C,
    0x1F83_D9AB,
    0x5BE0_CD19,
];

const BLAKE2S_SIGMA: [[usize; 16]; 10] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];

/// Focused incremental BLAKE2s implementation for the transition-key contract.
///
/// The parameter block is fixed to an eight-byte digest with the seven-byte
/// personalization `xykeyv1` (NUL-padded to BLAKE2s' eight-byte field).
struct Blake2s8 {
    state: [u32; 8],
    buffer: [u8; 64],
    buffered: usize,
    count: u64,
}

impl Blake2s8 {
    fn new() -> Self {
        let mut parameter = [0u8; 32];
        parameter[0] = 8; // digest length
        parameter[2] = 1; // fanout
        parameter[3] = 1; // depth
        parameter[24..31].copy_from_slice(b"xykeyv1");
        let mut state = BLAKE2S_IV;
        for (word, bytes) in state.iter_mut().zip(parameter.as_chunks::<4>().0) {
            *word ^= u32::from_le_bytes(*bytes);
        }
        Self {
            state,
            buffer: [0; 64],
            buffered: 0,
            count: 0,
        }
    }

    fn update(&mut self, mut input: &[u8]) {
        if self.buffered != 0 {
            let available = 64 - self.buffered;
            if input.len() <= available {
                self.buffer[self.buffered..self.buffered + input.len()].copy_from_slice(input);
                self.buffered += input.len();
                return;
            }
            self.buffer[self.buffered..].copy_from_slice(&input[..available]);
            self.count += 64;
            let block = self.buffer;
            self.compress(&block, false);
            self.buffered = 0;
            input = &input[available..];
        }
        while input.len() > 64 {
            self.count += 64;
            let block: &[u8; 64] = input[..64].try_into().expect("complete BLAKE2s block");
            self.compress(block, false);
            input = &input[64..];
        }
        self.buffer[..input.len()].copy_from_slice(input);
        self.buffered = input.len();
    }

    fn finish(mut self) -> [u8; 8] {
        self.count += self.buffered as u64;
        self.buffer[self.buffered..].fill(0);
        let block = self.buffer;
        self.compress(&block, true);
        let mut digest = [0u8; 8];
        digest[..4].copy_from_slice(&self.state[0].to_le_bytes());
        digest[4..].copy_from_slice(&self.state[1].to_le_bytes());
        digest
    }

    fn compress(&mut self, block: &[u8; 64], last: bool) {
        let mut message = [0u32; 16];
        for (word, bytes) in message.iter_mut().zip(block.as_chunks::<4>().0) {
            *word = u32::from_le_bytes(*bytes);
        }
        let mut work = [0u32; 16];
        work[..8].copy_from_slice(&self.state);
        work[8..].copy_from_slice(&BLAKE2S_IV);
        work[12] ^= self.count as u32;
        work[13] ^= (self.count >> 32) as u32;
        if last {
            work[14] = !work[14];
        }
        for schedule in BLAKE2S_SIGMA {
            blake2s_mix(
                &mut work,
                0,
                4,
                8,
                12,
                message[schedule[0]],
                message[schedule[1]],
            );
            blake2s_mix(
                &mut work,
                1,
                5,
                9,
                13,
                message[schedule[2]],
                message[schedule[3]],
            );
            blake2s_mix(
                &mut work,
                2,
                6,
                10,
                14,
                message[schedule[4]],
                message[schedule[5]],
            );
            blake2s_mix(
                &mut work,
                3,
                7,
                11,
                15,
                message[schedule[6]],
                message[schedule[7]],
            );
            blake2s_mix(
                &mut work,
                0,
                5,
                10,
                15,
                message[schedule[8]],
                message[schedule[9]],
            );
            blake2s_mix(
                &mut work,
                1,
                6,
                11,
                12,
                message[schedule[10]],
                message[schedule[11]],
            );
            blake2s_mix(
                &mut work,
                2,
                7,
                8,
                13,
                message[schedule[12]],
                message[schedule[13]],
            );
            blake2s_mix(
                &mut work,
                3,
                4,
                9,
                14,
                message[schedule[14]],
                message[schedule[15]],
            );
        }
        for index in 0..8 {
            self.state[index] ^= work[index] ^ work[index + 8];
        }
    }
}

#[inline(always)]
fn blake2s_mix(work: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize, x: u32, y: u32) {
    work[a] = work[a].wrapping_add(work[b]).wrapping_add(x);
    work[d] = (work[d] ^ work[a]).rotate_right(16);
    work[c] = work[c].wrapping_add(work[d]);
    work[b] = (work[b] ^ work[c]).rotate_right(12);
    work[a] = work[a].wrapping_add(work[b]).wrapping_add(y);
    work[d] = (work[d] ^ work[a]).rotate_right(8);
    work[c] = work[c].wrapping_add(work[d]);
    work[b] = (work[b] ^ work[c]).rotate_right(7);
}

#[inline]
fn digest_parts(parts: &[&[u8]]) -> [u8; 8] {
    let mut hasher = Blake2s8::new();
    for part in parts {
        hasher.update(part);
    }
    hasher.finish()
}

fn unsigned_decimal(mut value: u64, buffer: &mut [u8; 20]) -> &[u8] {
    let mut start = buffer.len();
    loop {
        start -= 1;
        buffer[start] = b'0' + (value % 10) as u8;
        value /= 10;
        if value == 0 {
            return &buffer[start..];
        }
    }
}

fn signed_decimal(value: i64, buffer: &mut [u8; 21]) -> &[u8] {
    let negative = value < 0;
    let mut magnitude = value.unsigned_abs();
    let mut start = buffer.len();
    loop {
        start -= 1;
        buffer[start] = b'0' + (magnitude % 10) as u8;
        magnitude /= 10;
        if magnitude == 0 {
            if negative {
                start -= 1;
                buffer[start] = b'-';
            }
            return &buffer[start..];
        }
    }
}

#[inline]
fn native_u32(bytes: &[u8], swap_endian: bool) -> u32 {
    let raw = u32::from_ne_bytes(bytes.try_into().expect("validated u32 width"));
    if swap_endian {
        raw.swap_bytes()
    } else {
        raw
    }
}

fn trim_byte_padding(row: &[u8]) -> &[u8] {
    let end = row
        .iter()
        .rposition(|&byte| byte != 0)
        .map_or(0, |index| index + 1);
    &row[..end]
}

fn trim_unicode_padding(row: &[u8], swap_endian: bool) -> &[u8] {
    let mut end = row.len();
    while end >= 4 && native_u32(&row[end - 4..end], swap_endian) == 0 {
        end -= 4;
    }
    &row[..end]
}

fn unsigned_value(row: &[u8], swap_endian: bool) -> Option<u64> {
    Some(match row.len() {
        1 => row[0] as u64,
        2 => {
            let raw = u16::from_ne_bytes(row.try_into().ok()?);
            if swap_endian {
                raw.swap_bytes() as u64
            } else {
                raw as u64
            }
        }
        4 => {
            let raw = u32::from_ne_bytes(row.try_into().ok()?);
            if swap_endian {
                raw.swap_bytes() as u64
            } else {
                raw as u64
            }
        }
        8 => {
            let raw = u64::from_ne_bytes(row.try_into().ok()?);
            if swap_endian {
                raw.swap_bytes()
            } else {
                raw
            }
        }
        _ => return None,
    })
}

fn signed_value(row: &[u8], swap_endian: bool) -> Option<i64> {
    Some(match row.len() {
        1 => row[0] as i8 as i64,
        2 => {
            let raw = u16::from_ne_bytes(row.try_into().ok()?);
            let native = if swap_endian { raw.swap_bytes() } else { raw };
            native as i16 as i64
        }
        4 => {
            let raw = u32::from_ne_bytes(row.try_into().ok()?);
            let native = if swap_endian { raw.swap_bytes() } else { raw };
            native as i32 as i64
        }
        8 => {
            let raw = u64::from_ne_bytes(row.try_into().ok()?);
            let native = if swap_endian { raw.swap_bytes() } else { raw };
            native as i64
        }
        _ => return None,
    })
}

fn unicode_digest(row: &[u8], swap_endian: bool) -> Option<[u8; 8]> {
    let codepoint_bytes = trim_unicode_padding(row, swap_endian);
    let mut hasher = Blake2s8::new();
    hasher.update(b"s:");
    for bytes in codepoint_bytes.as_chunks::<4>().0 {
        let scalar = char::from_u32(native_u32(bytes, swap_endian))?;
        let mut encoded = [0u8; 4];
        hasher.update(scalar.encode_utf8(&mut encoded).as_bytes());
    }
    Some(hasher.finish())
}

fn float_digest(bits: u64) -> Option<[u8; 8]> {
    let exponent_bits = ((bits >> 52) & 0x7ff) as i32;
    if exponent_bits == 0x7ff {
        return None;
    }
    let fraction = bits & 0x000f_ffff_ffff_ffff;
    let mut hasher = Blake2s8::new();
    hasher.update(b"f:");
    if bits >> 63 != 0 {
        hasher.update(b"-");
    }
    if exponent_bits == 0 && fraction == 0 {
        hasher.update(b"0x0.0p+0");
        return Some(hasher.finish());
    }
    hasher.update(if exponent_bits == 0 { b"0x0." } else { b"0x1." });
    let mut hexadecimal = [0u8; 13];
    for (index, digit) in hexadecimal.iter_mut().enumerate() {
        let shift = 48 - index * 4;
        let nibble = ((fraction >> shift) & 0xf) as u8;
        *digit = if nibble < 10 {
            b'0' + nibble
        } else {
            b'a' + nibble - 10
        };
    }
    hasher.update(&hexadecimal);
    hasher.update(b"p");
    let exponent = if exponent_bits == 0 {
        -1022
    } else {
        exponent_bits - 1023
    };
    if exponent >= 0 {
        hasher.update(b"+");
    }
    let mut exponent_buffer = [0u8; 21];
    hasher.update(signed_decimal(exponent as i64, &mut exponent_buffer));
    Some(hasher.finish())
}

fn row_digest(row: &[u8], kind: u32, swap_endian: bool) -> Result<[u8; 8], TransitionKeyError> {
    match kind {
        KIND_UNICODE => {
            unicode_digest(row, swap_endian).ok_or(TransitionKeyError::Invalid { index: None })
        }
        KIND_BYTES => Ok(digest_parts(&[b"y:", trim_byte_padding(row)])),
        KIND_BOOL => match row {
            [0] => Ok(digest_parts(&[b"b:0"])),
            [1] => Ok(digest_parts(&[b"b:1"])),
            _ => Err(TransitionKeyError::Invalid { index: None }),
        },
        KIND_SIGNED => {
            let value = signed_value(row, swap_endian)
                .ok_or(TransitionKeyError::Invalid { index: None })?;
            let mut decimal = [0u8; 21];
            Ok(digest_parts(&[b"i:", signed_decimal(value, &mut decimal)]))
        }
        KIND_UNSIGNED => {
            let value = unsigned_value(row, swap_endian)
                .ok_or(TransitionKeyError::Invalid { index: None })?;
            let mut decimal = [0u8; 20];
            Ok(digest_parts(&[
                b"i:",
                unsigned_decimal(value, &mut decimal),
            ]))
        }
        KIND_FLOAT64 => {
            let bits = unsigned_value(row, swap_endian)
                .ok_or(TransitionKeyError::Invalid { index: None })?;
            float_digest(bits).ok_or(TransitionKeyError::Invalid { index: None })
        }
        _ => Err(TransitionKeyError::Invalid { index: None }),
    }
}

fn rows_equal(first: &[u8], second: &[u8], kind: u32, swap_endian: bool) -> bool {
    match kind {
        KIND_UNICODE => {
            let first = trim_unicode_padding(first, swap_endian);
            let second = trim_unicode_padding(second, swap_endian);
            first.len() == second.len()
                && first
                    .as_chunks::<4>()
                    .0
                    .iter()
                    .zip(second.as_chunks::<4>().0)
                    .all(|(a, b)| native_u32(a, swap_endian) == native_u32(b, swap_endian))
        }
        KIND_BYTES => trim_byte_padding(first) == trim_byte_padding(second),
        KIND_BOOL => first == second,
        KIND_SIGNED => signed_value(first, swap_endian) == signed_value(second, swap_endian),
        KIND_UNSIGNED | KIND_FLOAT64 => {
            unsigned_value(first, swap_endian) == unsigned_value(second, swap_endian)
        }
        _ => false,
    }
}

fn valid_layout(kind: u32, width: usize) -> bool {
    match kind {
        KIND_UNICODE => width > 0 && width.is_multiple_of(4),
        KIND_BYTES => width > 0,
        KIND_BOOL => width == 1,
        KIND_SIGNED | KIND_UNSIGNED => matches!(width, 1 | 2 | 4 | 8),
        KIND_FLOAT64 => width == 8,
        _ => false,
    }
}

/// Encode homogeneous fixed-width rows into Python-compatible transition keys.
///
/// `data` must contain exactly `out_lo.len() * width` bytes. Outputs have equal
/// lengths and remain caller-owned. Duplicate and digest-collision errors carry
/// both the first conflicting row and the current row.
pub fn encode_fixed_into(
    data: &[u8],
    width: usize,
    kind: u32,
    swap_endian: bool,
    out_lo: &mut [u32],
    out_hi: &mut [u32],
) -> Result<(), TransitionKeyError> {
    if !valid_layout(kind, width)
        || out_lo.len() != out_hi.len()
        || data.len() != out_lo.len().saturating_mul(width)
    {
        return Err(TransitionKeyError::Invalid { index: None });
    }
    let mut seen: HashMap<[u8; 8], usize> = HashMap::with_capacity(out_lo.len());
    for (index, row) in data.chunks_exact(width).enumerate() {
        let digest = row_digest(row, kind, swap_endian)
            .map_err(|_| TransitionKeyError::Invalid { index: Some(index) })?;
        if let Some(&first) = seen.get(&digest) {
            let first_row = &data[first * width..(first + 1) * width];
            return Err(if rows_equal(first_row, row, kind, swap_endian) {
                TransitionKeyError::Duplicate { first, index }
            } else {
                TransitionKeyError::Collision { first, index }
            });
        }
        seen.insert(digest, index);
        out_lo[index] = u32::from_le_bytes(digest[..4].try_into().expect("low digest word"));
        out_hi[index] = u32::from_le_bytes(digest[4..].try_into().expect("high digest word"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encode(data: &[u8], len: usize, width: usize, kind: u32, swap: bool) -> Vec<[u32; 2]> {
        let mut low = vec![0; len];
        let mut high = vec![0; len];
        encode_fixed_into(data, width, kind, swap, &mut low, &mut high).unwrap();
        low.into_iter().zip(high).map(|(lo, hi)| [lo, hi]).collect()
    }

    #[test]
    fn blake2s_matches_python_personalized_vectors() {
        let vectors: &[(&[u8], [u8; 8])] = &[
            (b"", [0x4e, 0x9e, 0xba, 0xa7, 0x8f, 0x14, 0x9c, 0x5d]),
            (b"s:", [0xc5, 0x52, 0x69, 0xcf, 0x55, 0x7a, 0xc4, 0x6f]),
            (b"s:a", [0xb5, 0x2d, 0x83, 0x23, 0x79, 0x57, 0x39, 0x2a]),
            (b"y:a\0b", [0x88, 0xff, 0xa7, 0xb1, 0xba, 0x6c, 0x29, 0x9d]),
            (
                b"i:-9223372036854775808",
                [0x2b, 0x78, 0x46, 0x28, 0xf5, 0x8e, 0x4f, 0xcf],
            ),
        ];
        for &(token, expected) in vectors {
            assert_eq!(digest_parts(&[token]), expected, "{token:?}");
        }
    }

    #[test]
    fn blake2s_streaming_matches_python_across_block_boundaries() {
        let vectors = [
            (61, [0x3d, 0xe3, 0xd4, 0x9c, 0x05, 0xb3, 0x59, 0x15]),
            (62, [0x57, 0x81, 0xda, 0x6f, 0x90, 0x33, 0xb1, 0x60]),
            (63, [0x80, 0xca, 0x70, 0x13, 0x6f, 0x55, 0x55, 0xc5]),
            (64, [0xd1, 0x8e, 0xe0, 0xf2, 0x21, 0x08, 0xee, 0x9f]),
            (65, [0x6b, 0x19, 0x87, 0x55, 0x8c, 0x12, 0x3b, 0x0b]),
            (127, [0xc0, 0x1a, 0x03, 0xc8, 0x2c, 0x90, 0xaf, 0x19]),
            (128, [0xbd, 0x94, 0x43, 0xb6, 0xe4, 0x00, 0x84, 0x51]),
            (129, [0xda, 0x4d, 0x41, 0xce, 0xc8, 0x00, 0xd4, 0xcb]),
        ];
        for (length, expected) in vectors {
            let input = vec![b'z'; length];
            assert_eq!(digest_parts(&[&input]), expected, "length {length}");

            let split = length / 2;
            assert_eq!(
                digest_parts(&[&input[..split], &input[split..]]),
                expected,
                "split length {length}"
            );
        }
    }

    #[test]
    fn unicode_tokens_are_utf8_and_trim_only_padding() {
        let rows = [
            [0, 0, 0],
            [b'a' as u32, 0, 0],
            [0x00e9, 0, 0],
            [0x1f600, 0, 0],
            [b'a' as u32, 0, b'b' as u32],
        ];
        let bytes = rows
            .iter()
            .flatten()
            .flat_map(|value| value.to_ne_bytes())
            .collect::<Vec<_>>();
        let got = encode(&bytes, rows.len(), 12, KIND_UNICODE, false);
        assert_eq!(got[0], [0xcf69_52c5, 0x6fc4_7a55]); // s:
        assert_eq!(got[1], [0x2383_2db5, 0x2a39_5779]); // s:a
        assert_eq!(got[2], [0xd791_9aa5, 0xd070_c8b1]); // s:é
        assert_eq!(got[3], [0x44ec_c8f9, 0x5388_dfc6]); // s:😀
        assert_eq!(got[4], [0x86bf_c964, 0x0f9f_e2d2]); // s:a\0b
    }

    #[test]
    fn bytes_bool_and_integer_tokens_match_python() {
        let byte_rows = [
            b"\0\0\0".as_slice(),
            b"a\0\0".as_slice(),
            b"a\0b".as_slice(),
        ]
        .concat();
        let byte_keys = encode(&byte_rows, 3, 3, KIND_BYTES, false);
        assert_eq!(byte_keys[0], [0x62f6_fcd3, 0xab0a_595f]); // y:
        assert_eq!(byte_keys[1], [0x5b3b_753b, 0xe137_9b39]); // y:a
        assert_eq!(byte_keys[2], [0xb1a7_ff88, 0x9d29_6cba]); // y:a\0b

        let bool_keys = encode(&[0, 1], 2, 1, KIND_BOOL, false);
        assert_eq!(bool_keys[0], [0xd46a_5a74, 0x9fa0_77d4]);
        assert_eq!(bool_keys[1], [0x685f_68b3, 0x242e_6cc2]);

        let signed = [i64::MIN, -1, 0, 127];
        let signed_bytes = signed
            .iter()
            .flat_map(|value| value.to_ne_bytes())
            .collect::<Vec<_>>();
        let signed_keys = encode(&signed_bytes, signed.len(), 8, KIND_SIGNED, false);
        assert_eq!(signed_keys[0], [0x2846_782b, 0xcf4f_8ef5]);
        assert_eq!(signed_keys[1], [0x74f3_9158, 0x258f_5aee]);
        assert_eq!(signed_keys[2], [0x6a0d_2733, 0xd2c8_7bbd]);
        assert_eq!(signed_keys[3], [0x6673_71eb, 0xc533_1ccd]);

        let unsigned = u64::MAX.to_ne_bytes();
        assert_eq!(
            encode(&unsigned, 1, 8, KIND_UNSIGNED, false)[0],
            [0x1f5e_d8a5, 0xf8e0_8beb]
        );
    }

    #[test]
    fn byte_swapped_scalars_match_native_values() {
        let values = [i32::MIN, -17, 2048, i32::MAX];
        let native = values
            .iter()
            .flat_map(|value| value.to_ne_bytes())
            .collect::<Vec<_>>();
        let swapped = values
            .iter()
            .flat_map(|value| {
                let mut bytes = value.to_ne_bytes();
                bytes.reverse();
                bytes
            })
            .collect::<Vec<_>>();
        assert_eq!(
            encode(&native, values.len(), 4, KIND_SIGNED, false),
            encode(&swapped, values.len(), 4, KIND_SIGNED, true)
        );
    }

    #[test]
    fn float_tokens_match_python_hex_and_reject_nonfinite() {
        let values = [0.0f64, -0.0, 1.0, 0.5, f64::from_bits(1), f64::MAX];
        let bytes = values
            .iter()
            .flat_map(|value| value.to_ne_bytes())
            .collect::<Vec<_>>();
        let got = encode(&bytes, values.len(), 8, KIND_FLOAT64, false);
        let expected_tokens: [&[u8]; 6] = [
            b"f:0x0.0p+0",
            b"f:-0x0.0p+0",
            b"f:0x1.0000000000000p+0",
            b"f:0x1.0000000000000p-1",
            b"f:0x0.0000000000001p-1022",
            b"f:0x1.fffffffffffffp+1023",
        ];
        for (actual, token) in got.iter().zip(expected_tokens) {
            let digest = digest_parts(&[token]);
            assert_eq!(
                *actual,
                [
                    u32::from_le_bytes(digest[..4].try_into().unwrap()),
                    u32::from_le_bytes(digest[4..].try_into().unwrap()),
                ]
            );
        }
        let mut low = [0];
        let mut high = [0];
        assert_eq!(
            encode_fixed_into(
                &f64::NAN.to_ne_bytes(),
                8,
                KIND_FLOAT64,
                false,
                &mut low,
                &mut high,
            ),
            Err(TransitionKeyError::Invalid { index: Some(0) })
        );
    }

    #[test]
    fn duplicate_reports_first_and_current_rows() {
        let data = [7i16, -2, 7]
            .iter()
            .flat_map(|value| value.to_ne_bytes())
            .collect::<Vec<_>>();
        let mut low = [0; 3];
        let mut high = [0; 3];
        assert_eq!(
            encode_fixed_into(&data, 2, KIND_SIGNED, false, &mut low, &mut high),
            Err(TransitionKeyError::Duplicate { first: 0, index: 2 })
        );

        let padded = [b"a\0".as_slice(), b"a\0".as_slice()].concat();
        assert_eq!(
            encode_fixed_into(&padded, 2, KIND_BYTES, false, &mut low[..2], &mut high[..2]),
            Err(TransitionKeyError::Duplicate { first: 0, index: 1 })
        );
    }

    #[test]
    fn invalid_layouts_and_scalar_data_are_rejected() {
        let mut low = [0];
        let mut high = [0];
        assert!(matches!(
            encode_fixed_into(&[0; 3], 3, KIND_UNICODE, false, &mut low, &mut high),
            Err(TransitionKeyError::Invalid { index: None })
        ));
        assert!(matches!(
            encode_fixed_into(&[2], 1, KIND_BOOL, false, &mut low, &mut high),
            Err(TransitionKeyError::Invalid { index: Some(0) })
        ));
        let surrogate = 0xd800u32.to_ne_bytes();
        assert!(matches!(
            encode_fixed_into(&surrogate, 4, KIND_UNICODE, false, &mut low, &mut high),
            Err(TransitionKeyError::Invalid { index: Some(0) })
        ));
    }
}
