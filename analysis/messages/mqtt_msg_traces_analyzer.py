"""
MQTT Message Traces Analyzer
=============================
This script analyzes JSON trace files exported from MQTT clients (e.g., MQTTX).
It groups messages by minute-based time windows using the `createAt` field and
computes per-window and global statistics including:
  - Number of messages exchanged
  - Message rate (messages/second)
  - Average message size (bytes)
  - Average number of JSON properties in the payload

Usage:
    python mqtt_msg_traces_analyzer.py --file <path_to_json_file>
"""

import json
import argparse
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

# Default trace file path used when no command-line argument is provided.
DEFAULT_TRACE_FILE = "simulation_mockpt_traces.json"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_create_at(raw_timestamp: str) -> datetime:
    """
    Parse the custom timestamp format used in the trace file.
    Expected format: "YYYY-MM-DD HH:MM:SS:mmm" (last token is milliseconds).

    Args:
        raw_timestamp: The raw timestamp string from the JSON field `createAt`.

    Returns:
        A datetime object representing the parsed timestamp.
    """
    # The format uses ':' also before milliseconds, so we need to handle it
    # Example: "2025-11-18 15:53:49:331"
    parts = raw_timestamp.rsplit(":", 1)  # split off the milliseconds
    base_str = parts[0]  # "2025-11-18 15:53:49"
    millis = int(parts[1]) if len(parts) > 1 else 0
    dt = datetime.strptime(base_str, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(microsecond=millis * 1000)
    return dt


def minute_key(dt: datetime) -> str:
    """
    Return a string key representing the minute window for a given datetime.

    Args:
        dt: A datetime object.

    Returns:
        A string in the format "YYYY-MM-DD HH:MM".
    """
    return dt.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_trace_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Load the JSON trace file and return the raw data.

    Args:
        file_path: Path to the JSON file.

    Returns:
        The parsed JSON content (expected to be a list of connection objects).
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def extract_messages(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract all messages from every connection object in the trace data.

    Args:
        data: The raw JSON list of connection objects.

    Returns:
        A flat list containing all message dictionaries.
    """
    all_messages: List[Dict[str, Any]] = []
    for connection in data:
        messages = connection.get("messages", [])
        all_messages.extend(messages)
    return all_messages


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def group_messages_by_minute(messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group messages into minute-based time windows using their `createAt` field.

    Args:
        messages: A flat list of message dictionaries.

    Returns:
        A dictionary mapping minute keys ("YYYY-MM-DD HH:MM") to lists of
        messages that fall within that minute.
    """
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for msg in messages:
        raw_ts = msg.get("createAt", "")
        if not raw_ts:
            continue
        try:
            dt = parse_create_at(raw_ts)
            key = minute_key(dt)
            groups[key].append(msg)
        except (ValueError, IndexError) as e:
            print(f"[WARNING] Skipping message with unparseable createAt='{raw_ts}': {e}")
    return dict(groups)


# ---------------------------------------------------------------------------
# Statistics computation
# ---------------------------------------------------------------------------

def compute_payload_size(payload_str: str) -> int:
    """
    Compute the size in bytes of the payload string (UTF-8 encoded).

    Args:
        payload_str: The raw payload string.

    Returns:
        Size in bytes.
    """
    return len(payload_str.encode("utf-8"))


def _collect_hierarchical_keys(obj: Any, prefix: str = "") -> set:
    """
    Recursively traverse a JSON object and collect all property paths
    using dot-notation (e.g. "value.data.initial_x").
    Intermediate dict keys are included as well as leaf paths.
    Lists are traversed so that dict elements inside them are also explored.

    Args:
        obj: The current JSON node (dict, list, or scalar).
        prefix: The dot-separated path accumulated so far.

    Returns:
        A set of hierarchical property path strings.
    """
    keys: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.add(full_key)
            # Recurse into nested dicts / lists
            keys.update(_collect_hierarchical_keys(v, full_key))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_hierarchical_keys(item, prefix))
    return keys


def count_payload_properties(payload_str: str) -> int:
    """
    Count the total number of hierarchical properties in the JSON payload.
    The payload is navigated recursively; every key at every nesting level
    is counted (using dot-notation paths to avoid duplicates).
    If the payload is not valid JSON or not a JSON object, returns 0.

    Args:
        payload_str: The raw payload string.

    Returns:
        Number of unique hierarchical property paths in the JSON object.
    """
    try:
        obj = json.loads(payload_str)
        if isinstance(obj, dict):
            return len(_collect_hierarchical_keys(obj))
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


def extract_payload_property_names(payload_str: str) -> set:
    """
    Extract the full set of hierarchical property paths from the JSON payload
    using dot-notation (e.g. "value.data.initial_x").
    The entire JSON tree is navigated recursively.
    If the payload is not valid JSON or not a JSON object, returns an empty set.

    Args:
        payload_str: The raw payload string.

    Returns:
        A set of dot-notation property path strings.
    """
    try:
        obj = json.loads(payload_str)
        if isinstance(obj, dict):
            return _collect_hierarchical_keys(obj)
    except (json.JSONDecodeError, TypeError):
        pass
    return set()


def compute_time_span_seconds(messages: List[Dict[str, Any]]) -> float:
    """
    Compute the time span in seconds between the first and last message.

    Args:
        messages: List of message dictionaries.

    Returns:
        Time span in seconds (minimum 1.0 to avoid division by zero).
    """
    timestamps: List[datetime] = []
    for msg in messages:
        raw_ts = msg.get("createAt", "")
        if raw_ts:
            try:
                timestamps.append(parse_create_at(raw_ts))
            except (ValueError, IndexError):
                pass
    if len(timestamps) < 2:
        return 1.0  # avoid division by zero; single message ⇒ 1 second window
    time_delta = (max(timestamps) - min(timestamps)).total_seconds()
    return max(time_delta, 1.0)


def compute_window_stats(window_key: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute statistics for a single minute time window.

    Args:
        window_key: The minute key string identifying the window.
        messages: List of messages in this window.

    Returns:
        A dictionary with computed statistics for this window.
    """
    num_messages = len(messages)
    time_span_sec = compute_time_span_seconds(messages)

    # Message rate (messages per second)
    message_rate = num_messages / time_span_sec

    # Payload sizes, property counts, and unique property names
    sizes: List[int] = []
    prop_counts: List[int] = []
    unique_props: set = set()
    for msg in messages:
        payload = msg.get("payload", "")
        sizes.append(compute_payload_size(payload))
        prop_counts.append(count_payload_properties(payload))
        unique_props.update(extract_payload_property_names(payload))

    avg_size = sum(sizes) / num_messages if num_messages > 0 else 0.0
    avg_props = sum(prop_counts) / num_messages if num_messages > 0 else 0.0

    return {
        "window": window_key,
        "message_count": num_messages,
        "time_span_sec": round(time_span_sec, 3),
        "message_rate_per_sec": round(message_rate, 4),
        "avg_payload_size_bytes": round(avg_size, 2),
        "avg_payload_properties": round(avg_props, 2),
        "unique_property_count": len(unique_props),
        "unique_property_names": sorted(unique_props),
    }


def compute_global_stats(all_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute aggregate statistics over the entire file.

    Args:
        all_messages: The complete flat list of messages.

    Returns:
        A dictionary with global statistics.
    """
    num_messages = len(all_messages)
    if num_messages == 0:
        return {
            "total_messages": 0,
            "total_time_span_sec": 0,
            "global_message_rate_per_sec": 0,
            "global_avg_payload_size_bytes": 0,
            "global_avg_payload_properties": 0,
            "global_unique_property_count": 0,
            "global_unique_property_names": [],
        }

    time_span_sec = compute_time_span_seconds(all_messages)

    sizes: List[int] = []
    prop_counts: List[int] = []
    unique_props: set = set()
    for msg in all_messages:
        payload = msg.get("payload", "")
        sizes.append(compute_payload_size(payload))
        prop_counts.append(count_payload_properties(payload))
        unique_props.update(extract_payload_property_names(payload))

    return {
        "total_messages": num_messages,
        "total_time_span_sec": round(time_span_sec, 3),
        "global_message_rate_per_sec": round(num_messages / time_span_sec, 4),
        "global_avg_payload_size_bytes": round(sum(sizes) / num_messages, 2),
        "global_avg_payload_properties": round(sum(prop_counts) / num_messages, 2),
        "global_unique_property_count": len(unique_props),
        "global_unique_property_names": sorted(unique_props),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_separator(char: str = "-", length: int = 90) -> None:
    """Print a horizontal separator line."""
    print(char * length)


def print_window_stats(stats: Dict[str, Any]) -> None:
    """
    Print the statistics for a single time window in a readable format.

    Args:
        stats: Dictionary of computed statistics for one window.
    """
    print(f"  Window              : {stats['window']}")
    print(f"  Messages            : {stats['message_count']}")
    print(f"  Time span (sec)     : {stats['time_span_sec']}")
    print(f"  Message rate (msg/s): {stats['message_rate_per_sec']}")
    print(f"  Avg payload size (B): {stats['avg_payload_size_bytes']}")
    print(f"  Avg payload props   : {stats['avg_payload_properties']}")
    print(f"  Unique properties   : {stats['unique_property_count']}")
    print(f"  Property names      : {', '.join(stats['unique_property_names'])}")


def print_global_stats(stats: Dict[str, Any]) -> None:
    """
    Print the global (whole-file) statistics in a readable format.

    Args:
        stats: Dictionary of computed global statistics.
    """
    print(f"  Total messages            : {stats['total_messages']}")
    print(f"  Total time span (sec)     : {stats['total_time_span_sec']}")
    print(f"  Global message rate (msg/s): {stats['global_message_rate_per_sec']}")
    print(f"  Global avg payload size (B): {stats['global_avg_payload_size_bytes']}")
    print(f"  Global avg payload props   : {stats['global_avg_payload_properties']}")
    print(f"  Global unique properties   : {stats['global_unique_property_count']}")
    print(f"  Global property names      : {', '.join(stats['global_unique_property_names'])}")


def report(window_stats_list: List[Dict[str, Any]], global_stats: Dict[str, Any]) -> None:
    """
    Print a full report with per-window and global statistics.

    Args:
        window_stats_list: List of per-window stats dictionaries.
        global_stats: Global statistics dictionary.
    """
    print()
    print_separator("=")
    print("  MQTT MESSAGE TRACES ANALYSIS REPORT")
    print_separator("=")

    print()
    print(f"  Total time windows: {len(window_stats_list)}")
    print()
    print_separator()

    for ws in window_stats_list:
        print()
        print_window_stats(ws)
        print_separator()

    print()
    print_separator("=")
    print("  GLOBAL STATISTICS (entire file)")
    print_separator("=")
    print()
    print_global_stats(global_stats)
    print()
    print_separator("=")
    print()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        An argparse.Namespace with the parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Analyze MQTT message trace JSON files."
    )
    parser.add_argument(
        "--file",
        type=str,
        required=False,
        default=None,
        help="Path to the JSON trace file to analyze. "
             f"If omitted, defaults to '{DEFAULT_TRACE_FILE}'.",
    )
    return parser.parse_args()


def analyze(file_path: str) -> None:
    """
    Main analysis pipeline:
      1. Load the trace file.
      2. Extract all messages.
      3. Group messages by minute.
      4. Compute per-window statistics.
      5. Compute global statistics.
      6. Print the report.

    Args:
        file_path: Path to the JSON trace file.
    """
    # Step 1 – Load data
    print(f"[INFO] Loading trace file: {file_path}")
    data = load_trace_file(file_path)

    # Step 2 – Extract messages from all connections
    all_messages = extract_messages(data)
    print(f"[INFO] Total messages extracted: {len(all_messages)}")

    if not all_messages:
        print("[WARNING] No messages found in the trace file. Nothing to analyze.")
        return

    # Step 3 – Group by minute
    groups = group_messages_by_minute(all_messages)
    print(f"[INFO] Time windows (minutes) found: {len(groups)}")

    # Step 4 – Compute per-window statistics (sorted chronologically)
    window_stats_list: List[Dict[str, Any]] = []
    for key in sorted(groups.keys()):
        ws = compute_window_stats(key, groups[key])
        window_stats_list.append(ws)

    # Step 5 – Compute global statistics
    global_stats = compute_global_stats(all_messages)

    # Step 6 – Print the report
    report(window_stats_list, global_stats)


def main() -> None:
    """Entry point: parse arguments and run analysis."""
    args = parse_arguments()
    # Use the provided file path or fall back to the default constant
    file_path = args.file if args.file else DEFAULT_TRACE_FILE
    print(f"[INFO] Target file: {file_path}")
    analyze(file_path)


if __name__ == "__main__":
    main()

