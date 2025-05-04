# Bug Report: `note.save()` method produces empty text field in serialized output

## Issue Description

The `note.save()` method in gkeepapi does not properly include note text content when serializing notes to JSON. While the text content is accessible via the `note.text` attribute in the Python objects at runtime, when serializing with `note.save()`, the text field becomes an empty string `""` in the resulting data structure.

## Reproduction

This issue can be consistently reproduced with the following minimal test script:

```python
import gkeepapi
import keyring
import json

# Authenticate
keep = gkeepapi.Keep()
master_token = keyring.get_password("google-keep-token", "your_google_email@example.com")
keep.authenticate("your_google_email@example.com", master_token)

# Sync
keep.sync()

# Test with a note that has text
note = keep.all()[0]  # Get first note (or any note with text content)
print(f"Text directly from note.text: {note.text[:50]}...")  # Shows actual text content
print(f"Text length: {len(note.text)}")

# Now serialize using note.save()
serialized_note = note.save()
print(f"Text field after serialization: '{serialized_note.get('text', 'MISSING')}'")  # Shows empty string
```

## Diagnosis

I investigated this issue by writing a more detailed test script to analyze the problem:

```python
import gkeepapi
import keyring
import json

# Target a specific note known to have text content
TARGET_NOTE_ID = "your_note_id_here"  
SERVICE_NAME = "google-keep-token"

# Auth and Sync
keep = gkeepapi.Keep()
email = "your_email@example.com"
master_token = keyring.get_password(SERVICE_NAME, email)
keep.authenticate(email, master_token)
keep.sync()

# Check the note
note = keep.get(TARGET_NOTE_ID)
if note:
    print(f"Title: {note.title}")
    print(f"Text length: {len(note.text)}")
    print(f"Text (first 100 chars): {note.text[:100]}")
    
    # Check serialized version
    note_dict = json.loads(json.dumps(note.save(), indent=2))
    if 'text' in note_dict:
        print(f"Raw 'text' field in serialized data: '{note_dict['text']}'")
    else:
        print("No 'text' field found in serialized data!")
    
    # Look for text in other fields
    for key, value in note_dict.items():
        if isinstance(value, str) and len(value) > 20:
            print(f"Possible text content in field '{key}': '{value[:50]}...'")
```

This script confirmed:
1. The `note.text` attribute contains the correct text (length > 0)
2. When serialized with `note.save()`, the 'text' field exists but is always an empty string `""`
3. The text content doesn't appear to be stored in any other field in the serialized data

## Impact

This is a significant issue for applications that:
1. Download notes using gkeepapi
2. Serialize those notes using `note.save()` for storage or processing
3. Later reconstruct or display the notes from the serialized data

The serialized notes will not contain any of the actual note text content, rendering applications that process Google Keep notes ineffective.

## Workaround

I've implemented the following workaround in my code, which manually adds the text content back to the serialized data:

```python
# Get note data using save()
note_data = note.save()

# Fix the text field by manually copying from the note object
if hasattr(note, 'text') and note.text:
    note_data['text'] = note.text  # Use the actual text from the note object

# Now note_data has proper text content for serialization
```

## Environment

- Python version: 3.x
- gkeepapi version: [your version here, e.g., 0.14.2]
- Operating system: [your OS here]

## Additional Notes

- This appears to be a bug in the internal serialization logic of gkeepapi.
- The issue is consistent across different notes and gkeepapi sessions.
- I've checked multiple notes, and the problem persists for all of them.
- The issue doesn't seem to be related to the authentication method or caching.

## Questions

1. Is this a known issue with gkeepapi serialization?
2. Is there a preferred way to work around this issue while maintaining compatibility with the library?
3. Is there any update planned for this issue?

Thank you for your assistance! 