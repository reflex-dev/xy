---
name: setup-python-env
description: >
  Set up a Python virtual environment and install Reflex. Use when initializing a new Reflex project,
  setting up a development environment, or when the user needs to create a venv and install dependencies.
  Load when there is no .venv directory, when the user asks to start a new Reflex app, or when
  imports fail due to missing packages.
---

# Python Environment Setup for Reflex

This skill handles creating a Python virtual environment and installing Reflex.

## Step 1: Check for an existing virtual environment

Look for a `.venv` directory in the project root:

```bash
ls -d .venv 2>/dev/null
```

If `.venv` exists, activate it and skip to **Step 3**.

```bash
source .venv/bin/activate
```

## Step 2: Create the virtual environment

If no `.venv` exists, determine which tools are available.

### Option A: `uv` is available

Check if `uv` is installed:

```bash
uv --version
```

If `uv` is found:

1. If no `pyproject.toml` exists, initialize one:

   ```bash
   uv init --bare
   ```

2. Create the virtual environment:

   ```bash
   uv venv .venv
   ```

3. Activate it:

   ```bash
   source .venv/bin/activate
   ```

Skip to **Step 3**.

### Option B: Fall back to `python` / `pip`

If `uv` is not available, check the Python version:

```bash
python3 --version
```

If the version is **older than 3.10**, stop and inform the user:

> Python 3.10 or newer is required. Please install a more up-to-date version of Python before continuing.

If the version is **3.10 or newer**:

1. Create the virtual environment:

   ```bash
   python3 -m venv .venv
   ```

2. Activate it:

   ```bash
   source .venv/bin/activate
   ```

3. Upgrade pip:

   ```bash
   pip install --upgrade pip
   ```

## Step 3: Install Reflex

Check if Reflex is already installed:

```bash
pip show reflex 2>/dev/null
```

If Reflex is **not** installed:

### If using `uv`:

```bash
uv add reflex
```

### If using `pip`:

```bash
pip install reflex
```
