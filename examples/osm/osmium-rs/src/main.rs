//! `osm-nodes` — extract node coordinates from an `.osm.pbf` into two flat
//! `f64` column files.
//!
//! ```text
//! osm-nodes <planet.osm.pbf> <out_lon.f64> <out_lat.f64> [--threads N] [--capacity N]
//! ```

use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

use osmpbf_nodes::decode_pbf_nodes;

// Generous upper bound on planet node count (~9.5B as of 2026). The output
// files are sparse until written and truncated to the true count, so
// over-estimating costs nothing.
const DEFAULT_CAPACITY: u64 = 12_000_000_000;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mut positional: Vec<&str> = Vec::new();
    let mut threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let mut capacity = DEFAULT_CAPACITY;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--threads" | "-t" => {
                i += 1;
                threads = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(threads);
            }
            "--capacity" | "-c" => {
                i += 1;
                capacity = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(capacity);
            }
            "-h" | "--help" => {
                eprintln!(
                    "usage: osm-nodes <in.osm.pbf> <out_lon.f64> <out_lat.f64> \
                     [--threads N] [--capacity N]"
                );
                return ExitCode::SUCCESS;
            }
            other => positional.push(other),
        }
        i += 1;
    }

    if positional.len() != 3 {
        eprintln!("error: expected 3 paths (pbf, out_lon, out_lat); see --help");
        return ExitCode::FAILURE;
    }

    let (pbf, lon, lat) = (positional[0], positional[1], positional[2]);
    eprintln!("decoding {pbf} with {threads} threads (capacity {capacity})…");
    let t0 = Instant::now();
    match decode_pbf_nodes(
        Path::new(pbf),
        Path::new(lon),
        Path::new(lat),
        capacity,
        threads,
    ) {
        Ok(stats) => {
            let secs = t0.elapsed().as_secs_f64();
            eprintln!(
                "done: {} nodes in {:.1}s ({:.1} M nodes/s) across {} blocks{}",
                stats.nodes,
                secs,
                stats.nodes as f64 / secs / 1e6,
                stats.blocks,
                if stats.sparse_nodes > 0 {
                    format!("; WARNING {} non-dense nodes skipped", stats.sparse_nodes)
                } else {
                    String::new()
                },
            );
            // machine-readable last line
            println!("{}", stats.nodes);
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
