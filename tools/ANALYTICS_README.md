# KeepVault Analytics Dashboard 📊

A comprehensive Python tool that analyzes your notes in the KeepVault folder and generates a beautiful HTML dashboard with statistics, charts, and insights about your note-taking habits.

## Features ✨

### 🚀 **Core Analytics**
- 📈 **Cumulative Growth Timeline** - Track your knowledge base expansion
- 📅 **Multi-Timeframe Creation Patterns** - Daily/Weekly/Monthly note analysis
- 🎨 **Color Distribution Analysis** - Preferred note color patterns
- ☁️ **Word Cloud Visualization** - Most common topics and themes

### 🧠 **Advanced Intelligence**
- 🚀 **Writing Momentum Analysis** - Time gaps and creation velocity patterns
- 📝 **Writing Velocity Trends** - Quality and quantity evolution over time
- 🕒 **Activity Heatmap** - Peak productivity hours and days (FIXED!)
- 🌱 **Seasonal Writing Patterns** - Behavior across different seasons

### 🔗 **Network Science**
- 🧠 **Knowledge Network Centrality** - Find your most influential notes
- 🔗 **Link Density Analysis** - Inter-note connectivity metrics
- 🎯 **Knowledge Hubs** - Most referenced and connected content

### 📊 **Content Analytics**
- 📏 **Smart Length Categories** - Intelligent note size classification
- 🔧 **Content Structure Analysis** - Markdown element composition
- 📈 **Productivity Metrics** - Writing frequency and consistency
- 🎯 **Behavioral Insights** - Automated pattern recognition

## Installation

1. Make sure you're in the tools directory:
```bash
cd tools
```

2. Install required packages:
```bash
pip install -r requirements_analytics.txt
```

## Usage

### Basic Usage
Generate a dashboard with default settings:
```bash
python notes_analytics_dashboard.py
```

### Custom Vault Path
If your KeepVault folder is in a different location:
```bash
python notes_analytics_dashboard.py --vault-path /path/to/your/KeepVault
```

### Custom Output File
Specify a custom output filename:
```bash
python notes_analytics_dashboard.py --output my_dashboard.html
```

### Full Example
```bash
python notes_analytics_dashboard.py --vault-path ../KeepVault --output notes_report_2025.html
```

## What the Dashboard Shows

### 📊 Key Statistics
- Total number of notes
- Total word count across all notes
- Average words per note
- Notes creation timespan
- Active vs archived vs trashed notes
- Pinned notes count

### 📈 Visual Analytics (12+ Interactive Charts!)
1. **Cumulative Growth Timeline** - Shows total notes over time
2. **Multi-Timeframe Creation Patterns** - Daily/Weekly/Monthly breakdowns
3. **Activity Heatmap** - Peak productivity hours and days 🔥
4. **Writing Momentum Analysis** - Creative bursts and velocity
5. **Color Distribution Pie Chart** - Note color preferences
6. **Smart Length Categories** - Intelligent note size analysis
7. **Content Structure Breakdown** - Markdown elements analysis
8. **Writing Velocity Trends** - Quality evolution over time
9. **Seasonal Patterns** - Behavior across seasons
10. **Knowledge Hubs** - Most referenced notes
11. **Network Centrality** - Most influential content
12. **Word Cloud** - Topics and themes visualization

### 🧠 Smart Insights
- Assessment of your writing style (quick notes vs comprehensive)
- Most productive time periods
- Network analysis of note connections
- Preferred organizational patterns

## Example Output

When you run the tool, you'll see:
```
🧠 KeepVault Analytics Dashboard Generator
==================================================
Scanning vault: ../KeepVault
Found 905 markdown files
Successfully processed 905 notes

✅ Dashboard successfully generated!
📂 Open this file in your browser: /home/user/notes_dashboard.html
📊 Analyzed 905 notes
📝 Total words: 103,879
```

## Data Analysis

The tool analyzes:
- **Metadata**: Creation dates, colors, pinned status, archive state
- **Content**: Word counts, markdown structure, headings, lists
- **Links**: Internal `[[wiki-links]]` and external URLs
- **Structure**: File organization, naming patterns
- **Productivity**: Writing frequency and volume over time

## Privacy & Security

- All analysis is done **locally** on your machine
- No data is sent to external services
- The generated HTML file is completely self-contained
- You can safely share the dashboard (but check for sensitive content first!)

## Troubleshooting

### Missing Dependencies
If you get import errors:
```bash
pip install matplotlib seaborn pandas numpy wordcloud plotly PyYAML
```

### No Notes Found
Make sure the vault path is correct:
```bash
python notes_analytics_dashboard.py --vault-path /correct/path/to/KeepVault
```

### Permission Errors
Make sure the script is executable:
```bash
chmod +x notes_analytics_dashboard.py
```

## Customization

The tool is designed to be easily customizable. You can:
- Modify the color schemes in the CSS
- Add new chart types in the `generate_charts()` method
- Change the statistical calculations in `calculate_statistics()`
- Adjust the HTML template for different layouts

## Technical Details

- **Language**: Python 3.12+
- **Charts**: Plotly.js for interactive visualizations
- **Styling**: Bootstrap 5 + custom CSS
- **Data Processing**: Pandas, NumPy for analysis
- **Word Clouds**: WordCloud library
- **Metadata Parsing**: PyYAML for frontmatter

## 🆕 Recent Updates

### v2.0 - Ultra-Advanced Analytics (Latest)
- ✅ **FIXED**: Activity Heatmap now displays correctly with rich data
- 🚀 **NEW**: Multi-timeframe creation patterns (Daily/Weekly/Monthly)
- 🧠 **NEW**: Writing momentum and velocity analysis
- 📊 **NEW**: Network centrality and influence scoring
- 🌱 **NEW**: Seasonal writing pattern detection
- 📏 **NEW**: Smart note length categorization
- 🔧 **NEW**: Content structure analysis
- 📈 **NEW**: Advanced productivity metrics
- 🎯 **NEW**: Behavioral pattern recognition
- 💫 **ENHANCED**: 12+ interactive charts with professional styling

### v1.0 - Initial Release
- Basic timeline and color analysis
- Word count distributions
- Simple activity tracking
- Link analysis

---

Enjoy exploring your note-taking patterns! 🚀 