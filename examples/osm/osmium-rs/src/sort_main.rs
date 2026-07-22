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

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mut pos: Vec<&str> = Vec::new();
    let mut g = 8192usize;
    let mut parts = 512usize;
    // Default to the full planet extent; nodes fall within it.
    let (mut x0, mut x1, mut y0, mut y1) = (-180.0, 180.0, -90.0, 90.0);
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--grid" => {
                i += 1;
                g = args[i].parse().unwrap_or(g);
            }
            "--partitions" => {
                i += 1;
                parts = args[i].parse().unwrap_or(parts);
            }
            "--extent" => {
                x0 = args[i + 1].parse().unwrap();
                x1 = args[i + 2].parse().unwrap();
                y0 = args[i + 3].parse().unwrap();
                y1 = args[i + 4].parse().unwrap();
                i += 4;
            }
            other => pos.push(other),
        }
        i += 1;
    }
    if pos.len() != 3 {
        eprintln!("usage: osm-sort <lon.f64> <lat.f64> <out_prefix> [--grid G] [--partitions P]");
        return ExitCode::FAILURE;
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
