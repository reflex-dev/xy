---
name: reflex-process-management
description: >
  Manage Reflex application processes: compile to test, run the server in production mode,
  reload a running app by finding and restarting the app process, and manage logs for
  debugging. Use when the user wants to test, run, restart, or reload a Reflex app,
  when troubleshooting a running Reflex server, or when investigating errors.
---

# Reflex Process Management

This skill covers how to compile, run, and reload a Reflex application.

## Compiling (Testing the App)

To verify the app compiles without errors, run:

```bash
reflex compile --dry
```

This checks for syntax errors, import issues, and component problems without starting the server. Use this as a quick validation step after making changes.

## Running the Server

When instructed to run the Reflex server, always use production mode and redirect output to a log file:

```bash
reflex run --env prod --single-port 2>&1 | tee reflex.log
```

This command starts a long-running server process that **does not support hot reload** in production mode. Code changes will not be picked up automatically — you must stop and restart the server to apply changes (see **Reloading a Running App** below).

Using `2>&1 | tee reflex.log` captures both stdout and stderr to `reflex.log` while still printing to the terminal.

> **Important:** Always use `--env prod` unless the user explicitly requests development mode.

## Reloading a Running App

To reload the app without manually stopping and restarting from the terminal, follow these steps:

### Step 1: Determine the app port

Read `reflex.log` to find the port the app is listening on. Look for a line like `App running at: http://0.0.0.0:<port>`. Do not assume the port is 8000.

### Step 2: Find the app process

Using the port from Step 1, locate the **listening** process (not browser connections):

```bash
lsof -i :<port> -sTCP:LISTEN -t
```

The `-sTCP:LISTEN` flag is critical — it filters to only the server process that is _listening_ on the port, excluding browser or client connections. Without it, you may kill the user's browser.

If `lsof` is not available, use:

```bash
ss -tlnp | grep :<port>
```

Or:

```bash
fuser <port>/tcp
```

### Step 3: Send an interrupt signal

Send `SIGINT` (equivalent to Ctrl+C) to gracefully stop the process:

```bash
kill -INT $(lsof -i :<port> -sTCP:LISTEN -t)
```

If the process doesn't stop, escalate to `SIGTERM`:

```bash
kill -TERM $(lsof -i :<port> -sTCP:LISTEN -t)
```

### Step 4: Restart the server

Once the old process has exited, truncate the old log and start the server again:

```bash
> reflex.log
reflex run --env prod --single-port 2>&1 | tee reflex.log
```

## Investigating Errors

When the user reports an error, read `reflex.log` to find and diagnose the issue.
