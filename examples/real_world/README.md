# Real-world large-data notebooks

These six notebooks use public datasets large enough to exercise XY's density,
decimation, and faceting paths with recognizable scientific and operational
data:

| Notebook | Dataset | Default workload | XY path |
| --- | --- | ---: | --- |
| `01_gaia_hr_diagram.ipynb` | [ESA Gaia DR3](https://www.cosmos.esa.int/web/gaia-users/archive/programmatic-access) | 1M stars | scatter density |
| `02_gnomad_allele_frequency.ipynb` | [gnomAD v4.1 genomes](https://gnomad.broadinstitute.org/news/2024-04-gnomad-v4-1/) | up to 3.52M variants | scatter density + log axis |
| `03_pan_ukbb_manhattan.ipynb` | [Pan-UKBB standing-height GWAS](https://pan.ukbb.broadinstitute.org/downloads/index.html) | up to 2.64M variants | scatter density |
| `04_dukascopy_fx_ticks.ipynb` | [Dukascopy EUR/USD ticks](https://www.dukascopy.com/swiss/english/marketwatch/historical/) | five calendar days | M4 line decimation |
| `05_ligo_gw150914_strain.ipynb` | [GWOSC GW150914 strain](https://gwosc.org/events/GW150914/) | 16.8M samples | M4 line decimation |
| `06_nyc_taxi_density.ipynb` | [NYC TLC yellow-taxi pickups](https://data.cityofnewyork.us/d/2yzn-sicd) | 1M trips | density, hexbin, 24 facets |

## Screenshots

These are rendered chart outputs, not copies of the source datasets. The PNGs
below are the only data-derived artifacts checked in; each notebook downloads
its working rows from the linked public source into the git-ignored cache.

### 1. Gaia DR3 — Hertzsprung–Russell diagram

![Gaia DR3 stellar color versus absolute magnitude rendered as an XY scatter-density chart.](assets/01-gaia-hr-diagram.png)

**Theme:** Cosmic observatory · scatter density of stellar color versus
absolute magnitude

### 2. gnomAD v4.1 — allele frequency across the genome

![gnomAD allele frequency by chromosome rendered as an XY scatter-density chart with a logarithmic axis.](assets/02-gnomad-allele-frequency.png)

**Theme:** Clinical genomic atlas · scatter density of genomic position versus
allele frequency

### 3. Pan-UKBB — standing-height Manhattan plot

![Pan-UKBB standing-height associations across all autosomes rendered as an XY Manhattan plot.](assets/03-pan-ukbb-manhattan.png)

**Theme:** Warm biobank editorial · scatter density of genomic position versus
−log10 p-value

### 4. Dukascopy — EUR/USD tick history

![Dukascopy EUR/USD midpoint quotes rendered as an XY decimated line chart.](assets/04-dukascopy-fx-ticks.png)

**Theme:** Trading terminal · M4 line decimation of UTC time versus EUR/USD
midpoint

### 5. LIGO — GW150914 detector strain

![GWOSC's reconstructed Hanford waveform for GW150914 rendered as a signal-lab line chart showing inspiral, peak strain, and ringdown.](assets/05-ligo-gw150914-strain.png)

**Theme:** Signal-lab oscilloscope · a 16.8M-sample M4 overview, a bandpassed
detector detail, and the official GWOSC waveform reconstruction

### 6. NYC TLC — yellow-taxi pickup density

![Locally projected NYC yellow-taxi pickup coordinates rendered as a night-map hexbin-density chart with Midtown and airport callouts.](assets/06-nyc-taxi-density.png)

**Theme:** Night cartography · locally projected hexbin density using
`ln(1 + pickups / hex)`. The notebook also renders the same rows as automatic
scatter density and 24 hourly facets.

## Setup

From a Python 3.11+ environment:

```bash
python -m pip install xy jupyter numpy requests pysam h5py gwosc
jupyter lab
```

Open this directory in Jupyter and run a notebook from top to bottom. Each
notebook documents its official source, attribution notes, expected download,
and environment variables for scaling the workload.

Downloads and indexes are cached under `data/` by default. Set
`XY_REAL_WORLD_DATA=/absolute/path` to use a shared cache outside the checkout.
The directory is git-ignored.

Start with a smaller remote sample when checking connectivity:

```bash
GNOMAD_CHROMOSOMES=22 GNOMAD_WINDOWS=2 jupyter lab
PANUKBB_WINDOWS=2 PANUKBB_VARIANTS_PER_WINDOW=2000 jupyter lab
TLC_MAX_ROWS=1000000 jupyter lab
```

The notebooks intentionally keep acquisition separate from visualization.
Once a dataset is cached, chart cells can be rerun and restyled without another
download.
