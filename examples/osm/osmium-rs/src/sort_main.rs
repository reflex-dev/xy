//! `osm-sort` — build the spatial index (grid-bucketed f32 columns + offsets)
//! from canonical f64 lon/lat columns.
//!
//! ```text
//! osm-sort <lon.f64> <lat.f64> <out_prefix> [--grid G] [--partitions P] \
//!          [--extent x0 x1 y0 y1]
//! ```
//! Writes <out_prefix>.lon.f32, <out_prefix>.lat.f32, <out_prefix>.idx.

use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

use osmpbf_nodes::sort::spatial_sort;

const USAGE: &str =
    "usage: osm-sort <lon.f64> <lat.f64> <out_prefix> [--grid G] [--partitions P] [--extent x0 x1 y0 y1]";

fn usage(msg: &str) -> ExitCode {
    eprintln!("error: {msg}\n{USAGE}");
    ExitCode::FAILURE
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mut pos: Vec<&str> = Vec::new();
    let mut g = 8192usize;
    let mut parts = 512usize;
    // Default to the full planet extent; nodes fall within it.
    let (mut x0, mut x1, mut y0, mut y1) = (-180.0, 180.0, -90.0, 90.0);
    let mut i = 1;
    // Every option reads its values through `args.get(..).parse()`, so a flag at
    // the end of argv or a non-numeric value is a clean usage error — never an
    // out-of-bounds index or `unwrap` panic.
    while i < args.len() {
        match args[i].as_str() {
            "--grid" => match args.get(i + 1).and_then(|s| s.parse().ok()) {
                Some(v) => {
                    g = v;
                    i += 2;
                }
                None => return usage("--grid needs a positive integer"),
            },
            "--partitions" => match args.get(i + 1).and_then(|s| s.parse().ok()) {
                Some(v) => {
                    parts = v;
                    i += 2;
                }
                None => return usage("--partitions needs a positive integer"),
            },
            "--extent" => {
                let vals: Option<Vec<f64>> = (1..=4)
                    .map(|k| args.get(i + k).and_then(|s| s.parse().ok()))
                    .collect();
                match vals {
                    Some(v) => {
                        (x0, x1, y0, y1) = (v[0], v[1], v[2], v[3]);
                        i += 5;
                    }
                    None => return usage("--extent needs four numbers: x0 x1 y0 y1"),
                }
            }
            other => {
                pos.push(other);
                i += 1;
            }
        }
    }
    if pos.len() != 3 {
        return usage("expected exactly three positional args: <lon.f64> <lat.f64> <out_prefix>");
    }
    eprintln!("sorting into {g}x{g} grid, {parts} partitions, extent ({x0},{x1},{y0},{y1})…");
    let t0 = Instant::now();
    match spatial_sort(
        Path::new(pos[0]),
        Path::new(pos[1]),
        Path::new(pos[2]),
        g,
        x0,
        x1,
        y0,
        y1,
        parts,
    ) {
        Ok(s) => {
            let secs = t0.elapsed().as_secs_f64();
            eprintln!(
                "done: {} points, {}x{} grid, {} partitions (max {}) in {:.0}s ({:.1} M/s)",
                s.n,
                s.g,
                s.g,
                s.partitions,
                s.max_partition,
                secs,
                s.n as f64 / secs / 1e6,
            );
            println!("{}", s.n);
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
