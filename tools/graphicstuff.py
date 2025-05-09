import json
import datetime
from collections import Counter
import matplotlib.pyplot as plt
import numpy as np


def load_notes_data(filename='keep_notes.json'):
    """Loads notes data from the specified JSON file."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {filename} not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filename}.")
        return None


def plot_creation_timeline(notes_data):
    """
    Generates a line graph of note creations per day from 2024 onwards.
    """
    if not notes_data:
        return

    creation_dates = []
    for note in notes_data:
        try:
            timestamp_str = note.get('timestamps', {}).get('created')
            if timestamp_str:
                dt_object = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                creation_dates.append(dt_object.date())
        except Exception as e:
            print(f"Warning: Could not parse creation timestamp for a note (id: {note.get('id')}): {e}")

    if not creation_dates:
        print("No creation dates found.")
        return

    min_date = datetime.date(2024, 1, 1)
    creation_dates = [d for d in creation_dates if d >= min_date]

    if not creation_dates:
        print("No creation dates found from 2024 onwards for the timeline plot.")
        return

    date_counts = Counter(creation_dates)
    sorted_dates = sorted(date_counts.keys())

    if not sorted_dates:
        print("No data to plot for timeline after filtering.")
        return
        
    all_days_in_range = [sorted_dates[0] + datetime.timedelta(days=x) for x in range((sorted_dates[-1] - sorted_dates[0]).days + 1)]
    counts_for_all_days_in_range = {date: date_counts.get(date, 0) for date in all_days_in_range}
    final_sorted_days = sorted(counts_for_all_days_in_range.keys())
    final_counts = [counts_for_all_days_in_range[date] for date in final_sorted_days]

    plt.figure(figsize=(15, 7))
    plt.plot([dt.strftime('%Y-%m-%d') for dt in final_sorted_days], final_counts, marker='o', linestyle='-', color='dodgerblue')
    
    num_dates = len(final_sorted_days)
    if num_dates > 10:
        step = max(1, num_dates // 10)
        tick_positions = np.arange(0, num_dates, step)
        tick_labels = [final_sorted_days[i].strftime('%Y-%m-%d') for i in tick_positions]
        plt.xticks(ticks=tick_positions, labels=tick_labels, rotation=45, ha="right")
    elif num_dates > 0:
        plt.xticks(rotation=45, ha="right")

    plt.xlabel("Creation Date (from 2024)")
    plt.ylabel("Number of Notes Created")
    plt.title("Note Creations Over Time (from 2024)")
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.show()
    print("Displayed creation timeline. Close the graph window to see the next one (if any).")

def plot_label_distribution(notes_data):
    """Generates a pie chart of note distribution by labels."""
    if not notes_data:
        return

    label_counts = Counter()
    notes_with_labels = 0
    for note in notes_data:
        labels = note.get('labels')
        if labels: # Note has one or more labels
            notes_with_labels += 1
            for label_obj in labels:
                label_name = label_obj.get('name')
                if label_name:
                    label_counts[label_name] += 1
        # else: # Consider if you want to count notes with no labels
        #     label_counts['Notes without labels'] +=1 

    if not label_counts:
        print("No labels found in notes data to plot distribution.")
        return

    # Sort by count for better pie chart display, or use as is
    labels = list(label_counts.keys())
    counts = list(label_counts.values())

    plt.figure(figsize=(10, 8))
    # autopct displays the percentage on the pie chart slices
    # startangle rotates the start of the pie chart
    wedges, texts, autotexts = plt.pie(counts, labels=labels, autopct='%1.1f%%', startangle=140, pctdistance=0.85)
    plt.title(f'Distribution of Notes by Label (based on {sum(counts)} label instances across {notes_with_labels} notes)')
    plt.axis('equal') # Equal aspect ratio ensures that pie is drawn as a circle.
    
    # Add a legend if there are many labels
    if len(labels) > 5:
        plt.legend(wedges, labels, title="Labels", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
    
    plt.tight_layout()
    plt.show()
    print("Displayed label distribution. Close the graph window to see the next one (if any).")

def plot_text_length_distribution(notes_data):
    """Generates a histogram of note text lengths."""
    if not notes_data:
        return

    text_lengths = []
    for note in notes_data:
        text = note.get('text', '')
        # Consider if list items should have their text concatenated or counted differently
        # For now, just using the main 'text' field.
        if text: # Ensure text is not None
             text_lengths.append(len(text))
        else:
             text_lengths.append(0) # Count notes with no text as length 0

    if not text_lengths:
        print("No text found in notes to plot length distribution.")
        return

    plt.figure(figsize=(10, 6))
    # Define bins for the histogram, e.g., every 50 characters up to a reasonable max
    # Or let matplotlib decide the bins: plt.hist(text_lengths, bins='auto', color='lightcoral', edgecolor='black')
    max_len = max(text_lengths) if text_lengths else 0
    # Create somewhat dynamic bins, but not too many if max_len is huge
    num_bins = min(max(10, max_len // 100), 50) # Aim for 10-50 bins generally
    if max_len == 0: # Handle case with no text or all empty texts
        bins = [0, 1]
    elif max_len < 100:
        bins = np.arange(0, max_len + 10, 10) # Small bins for short notes
    else:
        bins = np.linspace(0, max_len, num_bins + 1) # Use linspace for larger ranges

    plt.hist(text_lengths, bins=bins, color='lightcoral', edgecolor='black')
    plt.title(f'Distribution of Note Text Lengths (Total notes: {len(text_lengths)})')
    plt.xlabel("Text Length (Number of Characters)")
    plt.ylabel("Number of Notes")
    plt.grid(axis='y', alpha=0.75)
    plt.tight_layout()
    plt.show()
    print("Displayed text length distribution. Close the graph window to see the next one (if any).")

def plot_color_distribution(notes_data):
    """Generates a pie chart of note distribution by color."""
    if not notes_data:
        return

    color_counts = Counter()
    for note in notes_data:
        color = note.get('color', 'DEFAULT') # 'DEFAULT' if color is not specified
        color_counts[color] += 1

    if not color_counts:
        print("No color information found in notes data.")
        return

    labels = list(color_counts.keys())
    counts = list(color_counts.values())
    # Define some friendly colors for common Keep colors, or use matplotlib defaults
    # This is optional and can be expanded.
    color_map = {
        'DEFAULT': 'lightgrey',
        'RED': '#FF8A80', # Light Red
        'ORANGE': '#FFD180', # Light Orange
        'YELLOW': '#FFFF8D', # Light Yellow
        'GREEN': '#CCFF90', # Light Green
        'TEAL': '#A7FFEB', # Light Teal
        'BLUE': '#80D8FF', # Light Blue
        'GRAY': '#CFD8DC', # Blue Grey 100
        # Add more Keep colors if known (PURPLE, PINK, BROWN)
        'PURPLE': '#D1C4E9',
        'PINK': '#F8BBD0',
        'BROWN': '#D7CCC8'
    }
    pie_colors = [color_map.get(label, plt.cm.get_cmap('viridis')(i/float(len(labels)))) for i, label in enumerate(labels)]


    plt.figure(figsize=(10, 8))
    wedges, texts, autotexts = plt.pie(counts, labels=labels, colors=pie_colors, autopct='%1.1f%%', startangle=140, pctdistance=0.85)
    plt.title(f'Distribution of Notes by Color (Total notes: {sum(counts)})')
    plt.axis('equal')

    if len(labels) > 5:
        plt.legend(wedges, labels, title="Colors", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))

    plt.tight_layout()
    plt.show()
    print("Displayed color distribution. Close the graph window to see the next one (if any).")


if __name__ == '__main__':
    notes = load_notes_data()
    if notes:
        plot_creation_timeline(notes)
        plot_label_distribution(notes)
        plot_text_length_distribution(notes)
        plot_color_distribution(notes)
        # Add calls to other plotting functions here as they are created
        print("All requested graphs have been displayed.")
    else:
        print("Could not load notes data. Exiting.") 