import re

def format_time(seconds_val):
    """Converts seconds to SRT time format (HH:MM:SS,ms)"""
    # Separate integer and fractional parts of seconds
    integer_seconds = int(seconds_val)
    fractional_seconds = seconds_val - integer_seconds

    # Calculate milliseconds, round, and handle carry-over to seconds
    millis = int(round(fractional_seconds * 1000))

    if millis >= 1000:
        integer_seconds += millis // 1000  # Add carried-over second(s)
        millis %= 1000                     # Remainder is the new milliseconds

    # Calculate HH, MM, SS from the (potentially adjusted) integer_seconds
    hours = integer_seconds // 3600
    remainder_after_hours = integer_seconds % 3600
    minutes = remainder_after_hours // 60
    final_seconds_part = remainder_after_hours % 60
    
    return f"{hours:02d}:{minutes:02d}:{final_seconds_part:02d},{millis:03d}"

def _parse_time_part(time_str_part):
    """Helper to parse a single time string like HH:MM:SS,ms or MM:SS,ms etc."""
    h, m, s, ms = 0, 0, 0, 0
    try:
        main_and_ms = time_str_part.split(',')
        if len(main_and_ms) != 2:
            # print(f"DEBUG: _parse_time_part: Invalid main/ms split for '{time_str_part}'")
            return None
        ms = int(main_and_ms[1])
        
        hms_parts = main_and_ms[0].split(':')
        if len(hms_parts) == 3: # HH:MM:SS
            h = int(hms_parts[0])
            m = int(hms_parts[1])
            s = int(hms_parts[2])
        elif len(hms_parts) == 2: # MM:SS
            m = int(hms_parts[0])
            s = int(hms_parts[1])
        elif len(hms_parts) == 1: # SS
            s = int(hms_parts[0])
        else:
            # print(f"DEBUG: _parse_time_part: Invalid h/m/s part count for '{main_and_ms[0]}'")
            return None
        
        # Basic validation for parsed values (optional, but good practice)
        if not (0 <= h <= 99 and 0 <= m <= 59 and 0 <= s <= 59 and 0 <= ms <= 999):
            # print(f"DEBUG: _parse_time_part: Parsed time values out of range for '{time_str_part}'")
            return None
            
        return h, m, s, ms
    except ValueError:
        # print(f"DEBUG: _parse_time_part: ValueError during int conversion for '{time_str_part}'")
        return None
    except Exception as e:
        # print(f"DEBUG: _parse_time_part: Generic error for '{time_str_part}': {e}")
        return None

def _normalize_timestamp_id(id_str):
    """Normalizes a timestamp ID string like 'HH:MM:SS,ms --> HH:MM:SS,ms' to a consistent format."""
    if not id_str or not isinstance(id_str, str):
        return f"ERROR_NORM_INVALID_INPUT_TYPE__{id_str}"
    
    id_str_stripped = id_str.strip()
    parts = id_str_stripped.split("-->")
    if len(parts) != 2:
        return f"ERROR_NORM_NO_ARROW_SEPARATOR__{id_str_stripped}"
        
    start_parsed = _parse_time_part(parts[0].strip())
    end_parsed = _parse_time_part(parts[1].strip())
    
    if not start_parsed:
        return f"ERROR_NORM_START_PARSE_FAILED__{id_str_stripped}"
    if not end_parsed:
        return f"ERROR_NORM_END_PARSE_FAILED__{id_str_stripped}"
        
    sh, sm, ss, sms = start_parsed
    eh, em, es, ems = end_parsed
    
    return (f"{sh:02d}:{sm:02d}:{ss:02d},{sms:03d} --> "
            f"{eh:02d}:{em:02d}:{es:02d},{ems:03d}")

def srt_time_to_seconds(time_str):
    """Converts SRT time format (HH:MM:SS,ms) to seconds."""
    parts = time_str.split(',')
    main_part = parts[0]
    ms = int(parts[1])
    h, m, s = map(int, main_part.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000 