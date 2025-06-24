import requests
from collections import defaultdict
import re
from datetime import datetime

playlist_urls = [
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/DaddyLive.m3u8",
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/DrewAll.m3u8",
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/PlutoTV.m3u8",
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/TubiTV.m3u8",
    # UDPTV_URL is handled separately for timestamp extraction, but also included
    # here so its channels are parsed and added to the merged playlist.
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/UDPTV.m3u",
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/TVPass.m3u",
    "http://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/DaddyLiveEvents.m3u8",
    "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/PPVLand.m3u8",
]

UDPTV_URL = "https://raw.githubusercontent.com/nene15/DrewLive/refs/heads/main/UDPTV.m3u"
EPG_URL = "https://tinyurl.com/merged2423-epg"
OUTPUT_FILE = "MergedPlaylist.m3u8"

def fetch_playlist(url):
    """
    Fetches raw playlist content from a URL and returns it as a list of lines.
    Includes robust error handling for network issues.
    """
    print(f"Attempting to fetch: {url}")
    try:
        res = requests.get(url, timeout=15) # Increased timeout slightly for larger files
        res.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        # Decode content with best available encoding, then strip whitespace and split
        return res.content.decode('utf-8', errors='ignore').strip().splitlines()
    except requests.exceptions.Timeout:
        print(f"❌ Failed to fetch {url}: Request timed out after 15 seconds.")
    except requests.exceptions.ConnectionError:
        print(f"❌ Failed to fetch {url}: Connection error (e.g., DNS failure, refused connection).")
    except requests.exceptions.HTTPError as err:
        print(f"❌ Failed to fetch {url}: HTTP Error {err.response.status_code} - {err.response.reason}")
    except Exception as e:
        print(f"❌ An unexpected error occurred while fetching {url}: {e}")
    return []

def extract_timestamp_from_udptv(lines):
    """
    Extracts the '# Last forced update:' line from UDPTV content.
    """
    for line in lines:
        if line.strip().startswith("# Last forced update:"):
            print(f"✅ Found UDPTV timestamp: {line.strip()}")
            return line.strip()
    print("⚠️ No '# Last forced update:' line found in UDPTV playlist.")
    return None

def parse_playlist(lines, source_url="Unknown"):
    """
    Parses M3U/M3U8 lines. Collects EXTINF, associated special headers, and URL.
    Returns a list of tuples: (extinf_line, tuple_of_headers, url_line).
    """
    parsed_channels = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:"):
            extinf_line = line
            channel_headers = [] # To store special headers like EXTVLCOPT, EXTGRP, etc.

            i += 1 # Move to the next line to find headers or URL

            # Collect any intermediate header lines associated with this channel
            # These are lines starting with '#' but not '#EXTINF:' itself.
            while i < len(lines) and lines[i].strip().startswith("#") and not lines[i].strip().startswith("#EXTINF:"):
                channel_headers.append(lines[i].strip())
                i += 1

            # The next line should be the stream URL
            if i < len(lines) and not lines[i].strip().startswith("#") and lines[i].strip():
                url_line = lines[i].strip()
                # Store (EXTINF, tuple(headers), URL) for uniqueness and easy writing
                parsed_channels.append((extinf_line, tuple(channel_headers), url_line))
                i += 1 # Consume the URL
            else:
                print(f"⚠️ Warning ({source_url}): #EXTINF at line {i} ('{extinf_line}') not followed by a valid stream URL. Skipping this entry.")
                # If no URL, we still consumed the EXTINF, so continue from current 'i'
                # The next iteration will pick up the current line, whether it's another EXTINF or something else.

        elif line.strip() == "" or line.startswith("#EXTM3U") or line.startswith("#EXT-X"):
            # Skip empty lines, #EXTM3U header, and HLS specific tags
            i += 1
        else:
            # Skip other unrecognized lines (e.g., general comments not associated with a channel)
            # print(f"DEBUG ({source_url}): Skipping unrecognized line: '{line}'") # Uncomment for verbose debugging
            i += 1
    print(f"✅ Parsed {len(parsed_channels)} channels from {source_url}.")
    return parsed_channels

def write_merged_playlist(all_unique_channels, timestamp_line):
    """
    Writes the merged playlist to the OUTPUT_FILE, sorted by group-title and then channel name.
    """
    lines = [
        f'#EXTM3U url-tvg="{EPG_URL}"'
    ]
    if timestamp_line:
        lines.append(timestamp_line)
    lines.append("") # Add a blank line for readability after initial headers

    # Prepare channels for sorting: (group, title, extinf, headers, url)
    sortable_channels = []
    for extinf, headers, url in all_unique_channels:
        group_match = re.search(r'group-title="([^"]+)"', extinf)
        group = group_match.group(1) if group_match else "Other"
        
        # Extract channel name from EXTINF for secondary sort
        title_match = re.search(r',([^,]+)$', extinf)
        title = title_match.group(1).strip() if title_match else ""
        
        sortable_channels.append((group.lower(), title.lower(), extinf, headers, url))

    # Sort primarily by group, then by channel title
    sorted_channels = sorted(sortable_channels)

    current_group = None
    total_channels_written = 0

    for group_lower, title_lower, extinf, headers, url in sorted_channels:
        # Get original group name from extinf if needed for display, otherwise use group_lower for comparison
        # For simplicity, we can just use the group name extracted and stored if consistency is key.
        # If the original EXTINF's group-title casing matters, you'd re-extract it here.
        # For now, sorting by lowercased group is fine, and we don't need a separate #EXTGRP header if it's already in EXTINF.
        
        # Add #EXTGRP header if the group changes (optional, but good for organization)
        # Re-extract actual group from extinf for the #EXTGRP line's casing
        group_match = re.search(r'group-title="([^"]+)"', extinf)
        actual_group_name = group_match.group(1) if group_match else "Other"

        if actual_group_name != current_group:
            if current_group is not None: # Add a blank line between different groups for visual separation
                lines.append("")
            lines.append(f'#EXTGRP:{actual_group_name}')
            current_group = actual_group_name
            
        lines.append(extinf)
        for hdr_line in headers: # Write the collected special headers
            lines.append(hdr_line)
        lines.append(url)
        total_channels_written += 1

    # Remove the last blank line if it was added unnecessarily after the last group
    if lines and lines[-1] == "":
        lines.pop()
    
    # Ensure file ends with a single newline
    final_output_string = '\n'.join(lines)
    if not final_output_string.endswith('\n'):
        final_output_string += '\n'

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(final_output_string)

    print(f"\n✅ Merged playlist written to {OUTPUT_FILE}.")
    print(f"📊 Total unique channels merged: {total_channels_written}.")
    print(f"📝 Total lines in output file: {len(final_output_string.splitlines())}.")

if __name__ == "__main__":
    print(f"Starting playlist merge at {datetime.now()}...")
    
    # Use a set to store unique channel tuples across all playlists
    # Each tuple will be: (extinf_line, tuple_of_headers, url_line)
    all_unique_channels_set = set()
    timestamp_line = None

    # 1. Handle UDPTV specifically for timestamp extraction and its channels
    print(f"\n--- Processing UDPTV playlist ({UDPTV_URL}) ---")
    udptv_raw_lines = fetch_playlist(UDPTV_URL)
    timestamp_line = extract_timestamp_from_udptv(udptv_raw_lines)
    
    # Parse UDPTV channels and add them to the set
    udptv_parsed_channels = parse_playlist(udptv_raw_lines, source_url=UDPTV_URL)
    all_unique_channels_set.update(udptv_parsed_channels)

    # 2. Fetch and parse all other playlists
    print("\n--- Processing other playlists ---")
    for url in playlist_urls:
        if url == UDPTV_URL: # Skip re-fetching UDPTV if it was already processed
            continue
        lines = fetch_playlist(url)
        parsed_channels = parse_playlist(lines, source_url=url)
        all_unique_channels_set.update(parsed_channels) # Add to the set

    # Convert the set of unique channels to a list to pass to write function
    # Sorting will happen inside write_merged_playlist
    write_merged_playlist(list(all_unique_channels_set), timestamp_line)
    print(f"Merging complete at {datetime.now()}.")
