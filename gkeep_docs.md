# Welcome to gkeepapi's documentation!

*   [Client Usage](#client-usage)
    *   [Authenticating](#authenticating)
    *   [Obtaining a Master Token](#obtaining-a-master-token)
    *   [Syncing](#syncing)
    *   [Caching notes](#caching-notes)
*   [Notes and Lists](#notes-and-lists)
    *   [Creating Notes](#creating-notes)
    *   [Getting Notes](#getting-notes)
    *   [Searching for Notes](#searching-for-notes)
    *   [Manipulating Notes](#manipulating-notes)
        *   [Getting Note content](#getting-note-content)
        *   [Getting List content](#getting-list-content)
        *   [Setting Note content](#setting-note-content)
        *   [Setting List content](#setting-list-content)
        *   [Setting List item position](#setting-list-item-position)
        *   [Sorting a List](#sorting-a-list)
        *   [Indent/dedent List items](#indentdedent-list-items)
    *   [Deleting Notes](#deleting-notes)
*   [Media](#media)
    *   [Accessing media](#accessing-media)
    *   [Fetching media](#fetching-media)
*   [Labels](#labels)
    *   [Getting Labels](#getting-labels)
    *   [Searching for Labels](#searching-for-labels)
    *   [Creating Labels](#creating-labels)
    *   [Editing Labels](#editing-labels)
    *   [Deleting Labels](#deleting-labels)
    *   [Manipulating Labels on Notes](#manipulating-labels-on-notes)
*   [Constants](#constants)
*   [Annotations](#annotations)
*   [Settings](#settings)
*   [Collaborators](#collaborators)
*   [Timestamps](#timestamps)
*   [FAQ](#faq)
*   [Known Issues](#known-issues)
*   [Debug](#debug)
*   [Notes](#notes-1)
    *   [Reporting errors](#reporting-errors)
*   [Indices and tables](#indices-and-tables)

**gkeepapi** is an unofficial client for programmatically interacting with Google Keep:

```python
import gkeepapi

# Obtain a master token for your account
master_token = '...'

keep = gkeepapi.Keep()
keep.authenticate('user@gmail.com', master_token)

note = keep.createNote('Todo', 'Eat breakfast')
note.pinned = True
note.color = gkeepapi.node.ColorValue.Red

keep.sync()

print(note.title)
print(note.text)
```

The client is mostly complete and ready for use, but there are some hairy spots. In particular, the interface for manipulating labels and blobs is subject to change.

# Client Usage

All interaction with Google Keep is done through a `Keep` object, which is responsible for authenticating, syncing changes and tracking modifications.

## Authenticating

The client uses the (private) mobile Google Keep API. A valid OAuth token is generated via `gpsoauth`, which requires a master token for the account. These tokens are so called because they have full access to your account. Protect them like you would a password:

```python
keep = gkeepapi.Keep()
keep.authenticate('user@gmail.com', master_token)
```

Rather than storing the token in the script, consider using your platform secrets store:

```python
import keyring

# To save the token
# ...
# keyring.set_password('google-keep-token', 'user@gmail.com', master_token)

master_token = keyring.get_password("google-keep-token", "user@gmail.com")
```

There is also a deprecated `Keep.login()` method which accepts a username and password. This is discouraged (and unlikely to work), due to increased security requirements on logins:

```python
keep.login('user@gmail.com', 'password')
```

## Obtaining a Master Token

Instructions can be found in the `gpsoauth` documentation. If you have Docker installed, the following one-liner prompts for the necessary information and outputs the token:

```bash
docker run --rm -it --entrypoint /bin/sh python:3 -c 'pip install gpsoauth; python3 -c '''print(__import__("gpsoauth").exchange_token(input("Email: "), input("OAuth Token: "), input("Android ID: ")))''
```

## Syncing

`gkeepapi` automatically pulls down all notes after authenticating. It takes care of refreshing API tokens, so there's no need to call `Keep.authenticate()` again. After making any local modifications to notes, make sure to call `Keep.sync()` to update them on the server!:

```python
keep.sync()
```

## Caching notes

The initial sync can take a while, especially if you have a lot of notes. To mitigate this, you can serialize note data to a file. The next time your program runs, it can resume from this state. This is handled via `Keep.dump()` and `Keep.restore()`:

```python
# Store cache
state = keep.dump()
fh = open('state', 'w')
json.dump(state, fh)
fh.close() # Added close

# Load cache
fh = open('state', 'r')
state = json.load(fh)
fh.close() # Added close
keep.restore(state)
```

You can also pass the state directly to the `Keep.authenticate()` and the (deprecated) `Keep.login()` methods:

```python
keep.authenticate(username, master_token, state=state)
keep.login(username, password, state=state)
```

# Notes and Lists

Notes and Lists are the primary types of notes visible to a Google Keep user. gkeepapi exposes these two notes via the `node.Note` and `node.List` classes. For Lists, there's also the `node.ListItem` class.

## Creating Notes

New notes are created with the `Keep.createNote()` and `Keep.createList()` methods. The Keep object keeps track of these objects and, upon `Keep.sync()`, will sync them if modifications have been made:

```python
gnote = keep.createNote('Title', 'Text')

glist = keep.createList('Title', [
    ('Item 1', False), # Not checked
    ('Item 2', True)  # Checked
])

# Sync up changes
keep.sync()
```

## Getting Notes

Notes can be retrieved via `Keep.get()` by their ID (visible in the URL when selecting a Note in the webapp):

```python
gnote = keep.get('...')
```

To fetch all notes, use `Keep.all()`:

```python
gnotes = keep.all()
```

## Searching for Notes

Notes can be searched for via `Keep.find()`:

```python
# Find by string
gnotes = keep.find(query='Title')

# Find by filter function
gnotes = keep.find(func=lambda x: x.deleted and x.title == 'Title')

# Find by labels
gnotes = keep.find(labels=[keep.findLabel('todo')])

# Find by colors
gnotes = keep.find(colors=[gkeepapi.node.ColorValue.White])

# Find by pinned/archived/trashed state
gnotes = keep.find(pinned=True, archived=False, trashed=False)
```

## Manipulating Notes

Note objects have many attributes that can be directly get and set. Here is a non-comprehensive list of the more interesting ones.

Notes and Lists:

*   `node.TopLevelNode.id` (Read only)
*   `node.TopLevelNode.parent` (Read only)
*   `node.TopLevelNode.title`
*   `node.TopLevelNode.text`
*   `node.TopLevelNode.color`
*   `node.TopLevelNode.archived`
*   `node.TopLevelNode.pinned`
*   `node.TopLevelNode.labels`
*   `node.TopLevelNode.annotations`
*   `node.TopLevelNode.timestamps` (Read only)
*   `node.TopLevelNode.collaborators`
*   `node.TopLevelNode.blobs` (Read only)
*   `node.TopLevelNode.drawings` (Read only)
*   `node.TopLevelNode.images` (Read only)
*   `node.TopLevelNode.audio` (Read only)

ListItems:

*   `node.ListItem.id` (Read only)
*   `node.ListItem.parent` (Read only)
*   `node.ListItem.parent_item` (Read only)
*   `node.ListItem.indented` (Read only)
*   `node.ListItem.text`
*   `node.ListItem.checked`

### Getting Note content

Example usage:

```python
print(gnote.title)
print(gnote.text)
```

### Getting List content

Retrieving the content of a list is slightly more nuanced as they contain multiple entries. To get a serialized version of the contents, simply access `node.List.text` as usual. To get the individual `node.ListItem` objects, access `node.List.items`:

```python
# Serialized content
print(glist.text)

# ListItem objects
glistitems = glist.items

# Checked ListItems
cglistitems = glist.checked

# Unchecked ListItems
uglistitems = glist.unchecked
```

### Setting Note content

Example usage:

```python
gnote.title = 'Title 2'
gnote.text = 'Text 2'
gnote.color = gkeepapi.node.ColorValue.White
gnote.archived = True
gnote.pinned = False
```

### Setting List content

New items can be added via `node.List.add()`:

```python
# Create a checked item
glist.add('Item 2', True)

# Create an item at the top of the list
glist.add('Item 1', True, gkeepapi.node.NewListItemPlacementValue.Top)

# Create an item at the bottom of the list
glist.add('Item 3', True, gkeepapi.node.NewListItemPlacementValue.Bottom)
```

Existing items can be retrieved and modified directly:

```python
glistitem = glist.items[0]
glistitem.text = 'Item 4'
glistitem.checked = True
```

Or deleted via `node.ListItem.delete()`:

```python
glistitem.delete()
```

### Setting List item position

To reposition an item (larger is closer to the top):

```python
# Set a specific sort id
glistitem1.sort = 42

# Swap the position of two items
val = glistitem2.sort
glistitem2.sort = glistitem3.sort
glistitem3.sort = val
```

### Sorting a List

Lists can be sorted via `node.List.sort_items()`:

```python
# Sorts items alphabetically by default
glist.sort_items()
```

### Indent/dedent List items

To indent a list item:

```python
gparentlistitem.indent(gchildlistitem)
```

To dedent:

```python
gparentlistitem.dedent(gchildlistitem)
```

## Deleting Notes

The `node.TopLevelNode.delete()` method marks the note for deletion (or undo):

```python
gnote.delete()
gnote.undelete()
```

To send the node to the trash instead (or undo):

```python
gnote.trash()
gnote.untrash()
```

# Media

Media blobs are images, drawings and audio clips that are attached to notes.

## Accessing media

Drawings:

*   `node.NodeDrawing.extracted_text` (Read only)

Images:

*   `node.NodeImage.width` (Read only)
*   `node.NodeImage.height` (Read only)
*   `node.NodeImage.byte_size` (Read only)
*   `node.NodeImage.extracted_text` (Read only)

Audio:

*   `node.NodeAudio.length` (Read only)

## Fetching media

To download media, you can use the `Keep.getMediaLink()` method to get a link:

```python
blob = gnote.images[0]
keep.getMediaLink(blob)
```

# Labels

Labels are short identifiers that can be assigned to notes. Labels are exposed via the `node.Label` class. Management is a bit unwieldy right now and is done via the `Keep` object. Like notes, labels are automatically tracked and changes are synced to the server.

## Getting Labels

Labels can be retrieved via `Keep.getLabel()` by their ID:

```python
label = keep.getLabel('...')
```

To fetch all labels, use `Keep.labels()`:

```python
labels = keep.labels()
```

## Searching for Labels

Most of the time, you'll want to find a label by name. For that, use `Keep.findLabel()`:

```python
label = keep.findLabel('todo')
```

Regular expressions are also supported here:

```python
import re # Added import
label = keep.findLabel(re.compile('^todo$'))
```

## Creating Labels

New labels can be created with `Keep.createLabel()`:

```python
label = keep.createLabel('todo')
```

## Editing Labels

A label's name can be updated directly:

```python
label.name = 'later'
```

## Deleting Labels

A label can be deleted with `Keep.deleteLabel()`. This method ensures the label is removed from all notes:

```python
keep.deleteLabel(label)
```

## Manipulating Labels on Notes

When working with labels and notes, the key point to remember is that we're always working with `node.Label` objects or IDs. Interaction is done through the `node.NodeLabels` class.

To add a label to a note:

```python
gnote.labels.add(label)
```

To check if a label is on a note:

```python
gnote.labels.get(label.id) != None
```

To remove a label from a note:

```python
gnote.labels.remove(label)
```

# Constants

*   `node.ColorValue` enumerates valid colors.
*   `node.CategoryValue` enumerates valid note categories.
*   `node.CheckedListItemsPolicyValue` enumerates valid policies for checked list items.
*   `node.GraveyardStateValue` enumerates valid visibility settings for checked list items.
*   `node.NewListItemPlacementValue` enumerates valid locations for new list items.
*   `node.NodeType` enumerates valid node types.
*   `node.BlobType` enumerates valid blob types.
*   `node.RoleValue` enumerates valid collaborator permissions.
*   `node.ShareRequestValue` enumerates vaild collaborator modification requests.
*   `node.SuggestValue` enumerates valid suggestion types.

# Annotations

READ ONLY TODO

# Settings

TODO

# Collaborators

Collaborators are users you've shared notes with. Access can be granted or revoked per note. Interaction is done through the `node.NodeCollaborators` class.

To add a collaborator to a note:

```python
gnote.collaborators.add(email)
```

To check if a collaborator has access to a note:

```python
email in gnote.collaborators.all()
```

To remove a collaborator from a note:

```python
gnote.collaborators.remove(email)
```

# Timestamps

All notes and lists have a `node.NodeTimestamps` object with timestamp data:

```python
node.timestamps.created
node.timestamps.deleted
node.timestamps.trashed
node.timestamps.updated
node.timestamps.edited
```

These timestamps are all read-only.

# FAQ

1.  **I get a "NeedsBrowser", "CaptchaRequired" or "BadAuthentication" `exception.LoginException` when I try to log in. (Not an issue when using Keep.authenticate())**

    This usually occurs when Google thinks the login request looks suspicious. Here are some steps you can take to resolve this:
    1.  Make sure you have the newest version of gkeepapi installed.
    2.  Instead of logging in every time, cache the authentication token and reuse it on subsequent runs. See here for an example implementation.
    3.  If you have 2-Step Verification turned on, generating an App Password for gkeepapi is highly recommended.
    4.  Upgrading to a newer version of Python (3.7+) has worked for some people. See this issue for more information.
    5.  If all else fails, try testing gkeepapi on a separate IP address and/or user to see if you can isolate the problem.

2.  **I get a "DeviceManagementRequiredOrSyncDisabled" `exception.LoginException` when I try to log in. (Not an issue when using Keep.authenticate())**

    This is due to the enforcement of Android device policies on your G-Suite account. To resolve this, you can try disabling that setting here.

3.  **My notes take a long time to sync**

    Follow the instructions in the [caching notes](#caching-notes) section and see if that helps. If you only need to update notes, you can try creating a new Google account. Share the notes to the new account and manage through there.

# Known Issues

1.  **`node.ListItem` consistency**

    The `Keep` class isn't aware of new `node.ListItem` objects till they're synced up to the server. In other words, `Keep.get()` calls for their IDs will fail.

# Debug

To enable development debug logs:

```python
gkeepapi.node.DEBUG = True
```

# Notes

*   Many sub-elements are read only.
*   `node.Node` specific `node.NewListItemPlacementValue` settings are not used.

## Reporting errors

Google occasionally ramps up changes to the Keep data format. When this happens, you'll likely get a `exception.ParseException`. Please report this on Github with the raw data, which you can grab like so:

```python
try:
    # Code that raises the exception
    pass # Added pass
except gkeepapi.exception.ParseException as e:
    print(e.raw)
```

If you're not getting an `exception.ParseException`, just a log line, make sure you've enabled debug mode.

# Indices and tables

*   Index
*   Module Index
*   Search Page

---
*Source: [https://gkeepapi.readthedocs.io/en/latest/](https://gkeepapi.readthedocs.io/en/latest/)* 