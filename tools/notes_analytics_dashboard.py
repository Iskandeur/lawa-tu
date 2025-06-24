#!/usr/bin/env python3
"""
KeepVault Notes Analytics Dashboard Generator

This tool analyzes notes in the KeepVault folder and generates a comprehensive
HTML dashboard with statistics, charts, and insights about your note-taking habits.

Features:
- Note creation and editing trends over time
- Content analysis (word counts, readability, topics)
- Metadata insights (colors, pinned status, archive patterns)
- Interactive charts and visualizations
- Network analysis of note connections
- Writing productivity metrics
"""

import os
import re
import yaml
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Set, Tuple
import argparse
import sys

# Check for required packages and install if missing
try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Wedge
    import seaborn as sns
    import pandas as pd
    import numpy as np
    from wordcloud import WordCloud
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    import plotly.offline as pyo
except ImportError as e:
    print(f"Missing required package: {e}")
    print("Please install required packages:")
    print("pip install matplotlib seaborn pandas numpy wordcloud plotly")
    sys.exit(1)

@dataclass
class NoteMetadata:
    """Represents metadata extracted from a note file"""
    id: str
    title: str
    color: str
    pinned: bool
    created: Optional[datetime]
    updated: Optional[datetime]
    edited: Optional[datetime]
    archived: bool
    trashed: bool
    file_path: str
    file_size: int
    word_count: int
    content_length: int
    line_count: int
    links_count: int
    headings_count: int
    list_items_count: int
    code_blocks_count: int
    internal_links: List[str]
    external_links: List[str]
    tags: List[str]

class NotesAnalyzer:
    """Main class for analyzing notes and generating insights"""
    
    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.notes: List[NoteMetadata] = []
        self.stats = {}
        
    def parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """Parse YAML frontmatter from markdown content"""
        if not content.startswith('---'):
            return {}, content
            
        try:
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                body = parts[2].strip()
                return frontmatter or {}, body
        except yaml.YAMLError:
            pass
        return {}, content
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse datetime string from various formats"""
        if not dt_str:
            return None
        
        # Handle different datetime formats
        formats = [
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d'
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
    
    def extract_links(self, content: str) -> Tuple[List[str], List[str]]:
        """Extract internal [[links]] and external [links](urls)"""
        # Internal wiki-style links
        internal_links = re.findall(r'\[\[([^\]]+)\]\]', content)
        
        # External markdown links
        external_pattern = r'\[([^\]]*)\]\(([^)]+)\)'
        external_matches = re.findall(external_pattern, content)
        external_links = [url for _, url in external_matches if url.startswith(('http', 'www'))]
        
        return internal_links, external_links
    
    def analyze_content(self, content: str) -> Dict:
        """Analyze markdown content for various metrics"""
        lines = content.split('\n')
        
        # Basic counts
        word_count = len(content.split())
        line_count = len(lines)
        content_length = len(content)
        
        # Markdown elements
        headings_count = len(re.findall(r'^#+\s', content, re.MULTILINE))
        list_items_count = len(re.findall(r'^\s*[-*+]\s', content, re.MULTILINE))
        code_blocks_count = len(re.findall(r'```', content)) // 2
        
        # Links
        internal_links, external_links = self.extract_links(content)
        links_count = len(internal_links) + len(external_links)
        
        return {
            'word_count': word_count,
            'line_count': line_count,
            'content_length': content_length,
            'headings_count': headings_count,
            'list_items_count': list_items_count,
            'code_blocks_count': code_blocks_count,
            'links_count': links_count,
            'internal_links': internal_links,
            'external_links': external_links
        }
    
    def process_note(self, file_path: Path) -> Optional[NoteMetadata]:
        """Process a single note file and extract metadata"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            frontmatter, body = self.parse_frontmatter(content)
            content_analysis = self.analyze_content(body)
            
            # Extract metadata with defaults
            note_id = frontmatter.get('id', str(file_path.stem))
            title = frontmatter.get('title', file_path.stem)
            color = frontmatter.get('color', 'White').upper()
            pinned = frontmatter.get('pinned', False)
            archived = frontmatter.get('archived', False)
            trashed = frontmatter.get('trashed', False)
            
            # Parse dates
            created = self.parse_datetime(frontmatter.get('created', ''))
            updated = self.parse_datetime(frontmatter.get('updated', ''))
            edited = self.parse_datetime(frontmatter.get('edited', ''))
            
            # File info
            file_size = file_path.stat().st_size
            
            # Tags (if any)
            tags = frontmatter.get('tags', [])
            if isinstance(tags, str):
                tags = [tags]
            
            return NoteMetadata(
                id=note_id,
                title=title,
                color=color,
                pinned=pinned,
                created=created,
                updated=updated,
                edited=edited,
                archived=archived,
                trashed=trashed,
                file_path=str(file_path),
                file_size=file_size,
                tags=tags,
                **content_analysis
            )
            
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            return None
    
    def scan_vault(self):
        """Scan the vault and process all notes"""
        print(f"Scanning vault: {self.vault_path}")
        
        markdown_files = list(self.vault_path.rglob("*.md"))
        print(f"Found {len(markdown_files)} markdown files")
        
        for file_path in markdown_files:
            note = self.process_note(file_path)
            if note:
                self.notes.append(note)
        
        print(f"Successfully processed {len(self.notes)} notes")
    
    def calculate_statistics(self):
        """Calculate comprehensive statistics"""
        if not self.notes:
            return
        
        # Basic stats
        total_notes = len(self.notes)
        active_notes = [n for n in self.notes if not n.archived and not n.trashed]
        archived_notes = [n for n in self.notes if n.archived]
        trashed_notes = [n for n in self.notes if n.trashed]
        pinned_notes = [n for n in self.notes if n.pinned]
        
        # Content stats
        total_words = sum(n.word_count for n in self.notes)
        total_size = sum(n.file_size for n in self.notes)
        avg_words_per_note = total_words / total_notes if total_notes > 0 else 0
        
        # Date-based stats
        notes_with_dates = [n for n in self.notes if n.created]
        if notes_with_dates:
            oldest_note = min(notes_with_dates, key=lambda x: x.created)
            newest_note = max(notes_with_dates, key=lambda x: x.created)
            date_range_days = (newest_note.created - oldest_note.created).days
        else:
            oldest_note = newest_note = None
            date_range_days = 0
        
        # Color distribution
        color_counts = Counter(n.color for n in self.notes)
        
        # Links analysis
        total_internal_links = sum(len(n.internal_links) for n in self.notes)
        total_external_links = sum(len(n.external_links) for n in self.notes)
        
        # Most connected notes
        link_targets = []
        for note in self.notes:
            link_targets.extend(note.internal_links)
        most_linked = Counter(link_targets).most_common(10)
        
        self.stats = {
            'basic': {
                'total_notes': total_notes,
                'active_notes': len(active_notes),
                'archived_notes': len(archived_notes),
                'trashed_notes': len(trashed_notes),
                'pinned_notes': len(pinned_notes)
            },
            'content': {
                'total_words': total_words,
                'total_size_mb': total_size / (1024 * 1024),
                'avg_words_per_note': avg_words_per_note,
                'total_internal_links': total_internal_links,
                'total_external_links': total_external_links
            },
            'dates': {
                'oldest_note': oldest_note.title if oldest_note else "N/A",
                'oldest_date': oldest_note.created.strftime('%Y-%m-%d') if oldest_note else "N/A",
                'newest_note': newest_note.title if newest_note else "N/A",
                'newest_date': newest_note.created.strftime('%Y-%m-%d') if newest_note else "N/A",
                'date_range_days': date_range_days
            },
            'colors': dict(color_counts),
            'most_linked': most_linked
        }
    
    def generate_charts(self) -> Dict[str, str]:
        """Generate various charts and return their HTML"""
        charts = {}
        
        # Set style
        plt.style.use('seaborn-v0_8')
        sns.set_palette("husl")
        
        # 1. Notes creation timeline (CUMULATIVE)
        if self.notes:
            dates_and_notes = [(n.created, n) for n in self.notes if n.created]
            if dates_and_notes:
                dates_and_notes.sort(key=lambda x: x[0])
                dates = [d for d, _ in dates_and_notes]
                
                # Create daily counts
                date_counts = Counter(d.date() for d in dates)
                sorted_dates = sorted(date_counts.keys())
                counts = [date_counts[d] for d in sorted_dates]
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=sorted_dates,
                    y=np.cumsum(counts),
                    mode='lines+markers',
                    name='Cumulative Notes',
                    line=dict(width=3, color='#2E86AB'),
                    marker=dict(size=6),
                    fill='tonexty'
                ))
                
                fig.update_layout(
                    title='📈 Cumulative Notes Over Time',
                    xaxis_title='Date',
                    yaxis_title='Total Number of Notes',
                    template='plotly_white',
                    height=400,
                    showlegend=False
                )
                
                charts['timeline'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 1b. Notes creation timeline (NON-CUMULATIVE - Daily/Weekly/Monthly)
        if self.notes:
            dates_and_notes = [(n.created, n) for n in self.notes if n.created]
            if dates_and_notes:
                dates = [d for d, _ in dates_and_notes]
                
                # Create different time aggregations
                daily_counts = Counter(d.date() for d in dates)
                weekly_counts = Counter(d.date() - timedelta(days=d.weekday()) for d in dates)
                monthly_counts = Counter(d.strftime('%Y-%m') for d in dates)
                
                # Create subplot with multiple views
                fig = make_subplots(
                    rows=3, cols=1,
                    subplot_titles=('Daily Note Creation', 'Weekly Note Creation', 'Monthly Note Creation'),
                    vertical_spacing=0.08
                )
                
                # Daily bars
                daily_dates = sorted(daily_counts.keys())
                daily_values = [daily_counts[d] for d in daily_dates]
                fig.add_trace(go.Bar(
                    x=daily_dates,
                    y=daily_values,
                    name='Daily',
                    marker_color='#3498db'
                ), row=1, col=1)
                
                # Weekly bars
                weekly_dates = sorted(weekly_counts.keys())
                weekly_values = [weekly_counts[d] for d in weekly_dates]
                fig.add_trace(go.Bar(
                    x=weekly_dates,
                    y=weekly_values,
                    name='Weekly',
                    marker_color='#e74c3c'
                ), row=2, col=1)
                
                # Monthly bars
                monthly_labels = sorted(monthly_counts.keys())
                monthly_values = [monthly_counts[m] for m in monthly_labels]
                fig.add_trace(go.Bar(
                    x=monthly_labels,
                    y=monthly_values,
                    name='Monthly',
                    marker_color='#2ecc71'
                ), row=3, col=1)
                
                fig.update_layout(
                    title='📊 Note Creation Patterns (Multiple Timeframes)',
                    template='plotly_white',
                    height=800,
                    showlegend=False
                )
                
                charts['creation_patterns'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 2. Color distribution pie chart
        if self.stats['colors']:
            colors_map = {
                'WHITE': '#F8F9FA',
                'YELLOW': '#FFC107',
                'GREEN': '#28A745',
                'BLUE': '#007BFF',
                'RED': '#DC3545',
                'ORANGE': '#FD7E14',
                'PINK': '#E83E8C',
                'PURPLE': '#6F42C1',
                'GRAY': '#6C757D'
            }
            
            labels = list(self.stats['colors'].keys())
            values = list(self.stats['colors'].values())
            colors = [colors_map.get(label, '#333333') for label in labels]
            
            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                marker_colors=colors,
                textinfo='label+percent',
                hole=0.3
            )])
            
            fig.update_layout(
                title='Note Colors Distribution',
                template='plotly_white',
                height=400
            )
            
            charts['colors'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 3. Word count distribution
        word_counts = [n.word_count for n in self.notes if n.word_count > 0]
        if word_counts:
            fig = go.Figure(data=[go.Histogram(
                x=word_counts,
                nbinsx=30,
                marker_color='#17A2B8',
                opacity=0.8
            )])
            
            fig.update_layout(
                title='Word Count Distribution',
                xaxis_title='Words per Note',
                yaxis_title='Number of Notes',
                template='plotly_white',
                height=400
            )
            
            charts['word_dist'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 4. Activity heatmap (notes created by day of week and hour) - FIXED
        if self.notes:
            created_dates = [n.created for n in self.notes if n.created]
            if created_dates:
                # Extract day of week and hour
                activity_data = []
                for dt in created_dates:
                    activity_data.append({
                        'day': dt.strftime('%A'),
                        'hour': dt.hour,
                        'date': dt.date()
                    })
                
                # Create heatmap data
                days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                hours = list(range(24))
                
                heatmap_data = np.zeros((len(days), len(hours)))
                
                for item in activity_data:
                    day_idx = days.index(item['day'])
                    hour_idx = item['hour']
                    heatmap_data[day_idx][hour_idx] += 1
                
                # Debug: print some info
                total_notes_with_time = len(activity_data)
                non_zero_cells = np.count_nonzero(heatmap_data)
                max_value = np.max(heatmap_data)
                
                # Convert to list for better JSON serialization
                heatmap_data_list = heatmap_data.tolist()
                
                fig = go.Figure(data=go.Heatmap(
                    z=heatmap_data_list,
                    x=hours,
                    y=days,
                    colorscale='Viridis',
                    showscale=True,
                    hoverongaps=False,
                    hovertemplate='<b>%{y}</b><br>Hour: %{x}:00<br>Notes: %{z}<extra></extra>',
                    zauto=False,
                    zmin=0,
                    zmax=max_value if max_value > 0 else 1
                ))
                
                fig.update_layout(
                    title=f'🕒 Activity Heatmap ({total_notes_with_time} notes, {non_zero_cells} active time slots, max: {max_value:.0f})',
                    xaxis_title='Hour of Day',
                    yaxis_title='Day of Week',
                    template='plotly_white',
                    height=400,
                    xaxis=dict(tickmode='linear', tick0=0, dtick=2),  # Show every 2 hours
                    yaxis=dict(tickmode='array', tickvals=list(range(7)), ticktext=days)
                )
                
                charts['heatmap'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 5. Advanced Analytics: Writing Velocity and Productivity Patterns
        if self.notes:
            dates_and_notes = [(n.created, n) for n in self.notes if n.created and n.word_count > 0]
            if len(dates_and_notes) > 5:  # Need enough data
                # Sort by date
                dates_and_notes.sort(key=lambda x: x[0])
                
                # Calculate rolling averages and trends
                window_size = min(7, len(dates_and_notes) // 4)  # Adaptive window
                dates = [x[0].date() for x in dates_and_notes]
                word_counts = [x[1].word_count for x in dates_and_notes]
                
                # Create rolling averages
                rolling_avg = []
                for i in range(len(word_counts)):
                    start_idx = max(0, i - window_size + 1)
                    avg = sum(word_counts[start_idx:i+1]) / (i - start_idx + 1)
                    rolling_avg.append(avg)
                
                fig = go.Figure()
                
                # Raw word counts
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=word_counts,
                    mode='markers',
                    name='Note Length',
                    marker=dict(size=8, color='#3498db', opacity=0.6),
                    hovertemplate='<b>%{x}</b><br>Words: %{y}<extra></extra>'
                ))
                
                # Rolling average
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=rolling_avg,
                    mode='lines',
                    name=f'{window_size}-Note Rolling Average',
                    line=dict(width=3, color='#e74c3c'),
                    hovertemplate='<b>%{x}</b><br>Avg Words: %{y:.1f}<extra></extra>'
                ))
                
                fig.update_layout(
                    title='📝 Writing Velocity & Quality Trends',
                    xaxis_title='Date',
                    yaxis_title='Words per Note',
                    template='plotly_white',
                    height=400,
                    legend=dict(x=0.02, y=0.98)
                )
                
                charts['writing_velocity'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 6. Content Structure Analysis
        if self.notes:
            structure_data = {
                'Lists': sum(n.list_items_count for n in self.notes),
                'Headings': sum(n.headings_count for n in self.notes),
                'Code Blocks': sum(n.code_blocks_count for n in self.notes),
                'Links': sum(n.links_count for n in self.notes)
            }
            
            # Calculate percentages
            total_elements = sum(structure_data.values())
            if total_elements > 0:
                fig = go.Figure(data=[go.Bar(
                    x=list(structure_data.keys()),
                    y=list(structure_data.values()),
                    marker_color=['#3498db', '#e74c3c', '#2ecc71', '#f39c12'],
                    text=[f'{v}<br>({v/total_elements*100:.1f}%)' for v in structure_data.values()],
                    textposition='auto'
                )])
                
                fig.update_layout(
                    title='📋 Content Structure Analysis',
                    xaxis_title='Element Type',
                    yaxis_title='Total Count',
                    template='plotly_white',
                    height=400,
                    showlegend=False
                )
                
                charts['structure'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 7. Note Length Distribution (Enhanced)
        if self.notes:
            word_counts = [n.word_count for n in self.notes if n.word_count > 0]
            if word_counts:
                # Create bins for different note types
                very_short = len([w for w in word_counts if w < 20])
                short = len([w for w in word_counts if 20 <= w < 100])
                medium = len([w for w in word_counts if 100 <= w < 500])
                long_notes = len([w for w in word_counts if 500 <= w < 2000])
                very_long = len([w for w in word_counts if w >= 2000])
                
                categories = ['Very Short<br>(0-19)', 'Short<br>(20-99)', 'Medium<br>(100-499)', 
                             'Long<br>(500-1999)', 'Very Long<br>(2000+)']
                counts = [very_short, short, medium, long_notes, very_long]
                colors = ['#e74c3c', '#f39c12', '#f1c40f', '#2ecc71', '#3498db']
                
                fig = go.Figure()
                
                # Add bars
                fig.add_trace(go.Bar(
                    x=categories,
                    y=counts,
                    marker_color=colors,
                    text=[f'{c}<br>({c/sum(counts)*100:.1f}%)' for c in counts],
                    textposition='auto'
                ))
                
                fig.update_layout(
                    title='📏 Note Length Distribution (Smart Categories)',
                    xaxis_title='Note Length Category',
                    yaxis_title='Number of Notes',
                    template='plotly_white',
                    height=400,
                    showlegend=False
                )
                
                charts['smart_word_dist'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 8. Top connected notes (Enhanced)
        if self.stats['most_linked']:
            titles, counts = zip(*self.stats['most_linked'][:10])
            
            fig = go.Figure(data=[go.Bar(
                x=counts,
                y=titles,
                orientation='h',
                marker_color='#20C997',
                text=counts,
                textposition='auto'
            )])
            
            fig.update_layout(
                title='🔗 Knowledge Hubs (Most Referenced Notes)',
                xaxis_title='Number of References',
                yaxis_title='Note Title',
                template='plotly_white',
                height=400,
                yaxis={'categoryorder': 'total ascending'}
            )
            
            charts['top_linked'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 9. INNOVATIVE: Note Creation Momentum Analysis
        if self.notes:
            dates_and_notes = [(n.created, n) for n in self.notes if n.created]
            if len(dates_and_notes) > 10:  # Need enough data
                dates_and_notes.sort(key=lambda x: x[0])
                
                # Calculate time gaps between notes
                time_gaps = []
                for i in range(1, len(dates_and_notes)):
                    gap = (dates_and_notes[i][0] - dates_and_notes[i-1][0]).total_seconds() / 3600  # hours
                    time_gaps.append(min(gap, 168))  # Cap at 1 week for visualization
                
                # Create momentum score (inverse of time gap)
                momentum_scores = [168 / (gap + 1) for gap in time_gaps]
                dates_for_momentum = [x[0].date() for x in dates_and_notes[1:]]
                
                fig = go.Figure()
                
                # Momentum line
                fig.add_trace(go.Scatter(
                    x=dates_for_momentum,
                    y=momentum_scores,
                    mode='lines+markers',
                    name='Creation Momentum',
                    line=dict(width=2, color='#9b59b6'),
                    fill='tonexty',
                    fillcolor='rgba(155, 89, 182, 0.1)'
                ))
                
                # Add trend line
                if len(momentum_scores) > 3:
                    x_numeric = [(d - dates_for_momentum[0]).days for d in dates_for_momentum]
                    z = np.polyfit(x_numeric, momentum_scores, 1)
                    trend_line = np.poly1d(z)
                    
                    fig.add_trace(go.Scatter(
                        x=dates_for_momentum,
                        y=trend_line(x_numeric),
                        mode='lines',
                        name='Trend',
                        line=dict(width=2, color='#e74c3c', dash='dash')
                    ))
                
                fig.update_layout(
                    title='🚀 Note Creation Momentum (Higher = More Frequent)',
                    xaxis_title='Date',
                    yaxis_title='Momentum Score',
                    template='plotly_white',
                    height=400
                )
                
                charts['momentum'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 10. ULTRA-NERDY: Seasonal and Cyclical Patterns
        if self.notes:
            dates_with_data = [(n.created, n) for n in self.notes if n.created]
            if len(dates_with_data) > 30:  # Need substantial data
                # Extract temporal features
                temporal_data = []
                for dt, note in dates_with_data:
                    temporal_data.append({
                        'month': dt.month,
                        'day_of_week': dt.weekday(),
                        'hour': dt.hour,
                        'quarter': (dt.month - 1) // 3 + 1,
                        'season': ['Winter', 'Winter', 'Spring', 'Spring', 'Spring', 
                                  'Summer', 'Summer', 'Summer', 'Fall', 'Fall', 'Fall', 'Winter'][dt.month - 1],
                        'word_count': note.word_count
                    })
                
                # Create seasonal analysis
                seasonal_counts = Counter(item['season'] for item in temporal_data)
                seasonal_words = defaultdict(list)
                for item in temporal_data:
                    seasonal_words[item['season']].append(item['word_count'])
                
                seasons = ['Spring', 'Summer', 'Fall', 'Winter']
                counts = [seasonal_counts.get(s, 0) for s in seasons]
                avg_words = [np.mean(seasonal_words[s]) if seasonal_words[s] else 0 for s in seasons]
                
                fig = make_subplots(
                    rows=1, cols=2,
                    subplot_titles=('Notes per Season', 'Average Words per Season'),
                    specs=[[{"secondary_y": False}, {"secondary_y": False}]]
                )
                
                # Notes count
                fig.add_trace(go.Bar(
                    x=seasons,
                    y=counts,
                    name='Note Count',
                    marker_color=['#2ecc71', '#f39c12', '#e67e22', '#3498db']
                ), row=1, col=1)
                
                # Average words
                fig.add_trace(go.Bar(
                    x=seasons,
                    y=avg_words,
                    name='Avg Words',
                    marker_color=['#27ae60', '#f1c40f', '#d35400', '#2980b9']
                ), row=1, col=2)
                
                fig.update_layout(
                    title='🌱 Seasonal Writing Patterns',
                    template='plotly_white',
                    height=400,
                    showlegend=False
                )
                
                charts['seasonal'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        # 11. SUPER NERDY: Link Network Centrality Analysis
        if self.notes:
            # Build network graph
            link_network = defaultdict(set)
            note_titles = {n.title: n for n in self.notes if n.title}
            
            for note in self.notes:
                for link in note.internal_links:
                    if link in note_titles:
                        link_network[note.title].add(link)
                        link_network[link].add(note.title)  # Bidirectional
            
            if len(link_network) > 5:
                # Calculate centrality metrics
                centrality_scores = {}
                for note_title in link_network:
                    # Simple degree centrality
                    degree = len(link_network[note_title])
                    
                    # Calculate "influence" (2nd degree connections)
                    second_degree = set()
                    for connected_note in link_network[note_title]:
                        second_degree.update(link_network.get(connected_note, set()))
                    second_degree.discard(note_title)  # Remove self
                    influence = len(second_degree)
                    
                    centrality_scores[note_title] = {
                        'degree': degree,
                        'influence': influence,
                        'total_score': degree * 2 + influence
                    }
                
                # Get top influential notes
                top_influential = sorted(centrality_scores.items(), 
                                       key=lambda x: x[1]['total_score'], reverse=True)[:10]
                
                if top_influential:
                    titles = [item[0][:30] + '...' if len(item[0]) > 30 else item[0] 
                             for item in top_influential]
                    scores = [item[1]['total_score'] for item in top_influential]
                    
                    fig = go.Figure(data=[go.Bar(
                        x=scores,
                        y=titles,
                        orientation='h',
                        marker_color='#8e44ad',
                        text=scores,
                        textposition='auto'
                    )])
                    
                    fig.update_layout(
                        title='🧠 Knowledge Network Influence (Centrality Analysis)',
                        xaxis_title='Influence Score (Direct + Indirect Connections)',
                        yaxis_title='Note Title',
                        template='plotly_white',
                        height=500,
                        yaxis={'categoryorder': 'total ascending'}
                    )
                    
                    charts['network_centrality'] = pyo.plot(fig, output_type='div', include_plotlyjs=False)
        
        return charts
    
    def generate_word_cloud(self) -> str:
        """Generate a word cloud from note titles and content"""
        try:
            # Combine all titles and extract words
            all_text = []
            
            # Add titles
            for note in self.notes:
                if note.title and not note.title.startswith('Untitled'):
                    all_text.append(note.title)
            
            # Add internal links (most mentioned topics)
            for note in self.notes:
                all_text.extend(note.internal_links)
            
            if not all_text:
                return ""
            
            text = ' '.join(all_text)
            
            # Remove common words and clean
            text = re.sub(r'\b(the|and|or|but|in|on|at|to|for|of|with|by|a|an)\b', '', text, flags=re.IGNORECASE)
            text = re.sub(r'[^\w\s]', '', text)
            
            if len(text.strip()) < 10:
                return ""
            
            wordcloud = WordCloud(
                width=800, 
                height=400, 
                background_color='white',
                colormap='viridis',
                max_words=100,
                relative_scaling=0.5,
                stopwords=set(['untitled', 'note', 'notes', 'md'])
            ).generate(text)
            
            # Save to base64
            import io
            import base64
            
            plt.figure(figsize=(12, 6))
            plt.imshow(wordcloud, interpolation='bilinear')
            plt.axis('off')
            plt.title('Most Common Topics and Titles', fontsize=16, pad=20)
            
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', bbox_inches='tight', dpi=150)
            buffer.seek(0)
            
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            plt.close()
            
            return f'<img src="data:image/png;base64,{img_base64}" style="width: 100%; max-width: 800px;">'
            
        except Exception as e:
            print(f"Error generating word cloud: {e}")
            return ""
    
    def generate_dashboard(self, output_file: str = "notes_dashboard.html"):
        """Generate the complete HTML dashboard"""
        
        # Calculate stats and generate charts
        self.calculate_statistics()
        charts = self.generate_charts()
        wordcloud_html = self.generate_word_cloud()
        
        # Create HTML template
        html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KeepVault Analytics Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body {{
            background-color: #f8f9fa;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }}
        .dashboard-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem 0;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: white;
            border-radius: 15px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }}
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        .stat-number {{
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }}
        .stat-label {{
            color: #6c757d;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .chart-container {{
            background: white;
            border-radius: 15px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .insight-card {{
            background: linear-gradient(135deg, #ffeaa7 0%, #fab1a0 100%);
            border-radius: 15px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            color: #2d3436;
        }}
        .wordcloud-container {{
            text-align: center;
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
    </style>
</head>
<body>
    <div class="dashboard-header">
        <div class="container">
            <h1 class="display-4 text-center">
                <i class="fas fa-brain me-3"></i>
                KeepVault Analytics Dashboard
            </h1>
            <p class="lead text-center">Insights into your note-taking journey</p>
            <p class="text-center">Generated on {timestamp}</p>
        </div>
    </div>
    
    <div class="container">
        <!-- Key Statistics -->
        <div class="row">
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-primary">{total_notes}</div>
                    <div class="stat-label">Total Notes</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-success">{total_words:,}</div>
                    <div class="stat-label">Total Words</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-info">{avg_words:.0f}</div>
                    <div class="stat-label">Avg Words/Note</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-warning">{date_range}</div>
                    <div class="stat-label">Days Active</div>
                </div>
            </div>
        </div>
        
        <!-- Status Overview -->
        <div class="row">
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-success">{active_notes}</div>
                    <div class="stat-label"><i class="fas fa-file-alt"></i> Active</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-secondary">{archived_notes}</div>
                    <div class="stat-label"><i class="fas fa-archive"></i> Archived</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-danger">{trashed_notes}</div>
                    <div class="stat-label"><i class="fas fa-trash"></i> Trashed</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card text-center">
                    <div class="stat-number text-warning">{pinned_notes}</div>
                    <div class="stat-label"><i class="fas fa-thumbtack"></i> Pinned</div>
                </div>
            </div>
        </div>
        
        <!-- Insights -->
        <div class="row">
            <div class="col-12">
                <div class="insight-card">
                    <h4><i class="fas fa-lightbulb me-2"></i>Advanced Data Insights</h4>
                    <ul class="mb-0">
                        <li>📅 <strong>Writing Frequency:</strong> {frequency_assessment} over {date_range} days</li>
                        <li>🎯 <strong>Productivity Rate:</strong> {productivity_rate:.1f}% of days active</li>
                        <li>📝 <strong>Note Style:</strong> {avg_words:.0f} avg words - {length_assessment}</li>
                        <li>🔗 <strong>Network Density:</strong> {link_density:.1f} links/note - {link_assessment}</li>
                        <li>🎨 <strong>Color Preference:</strong> {popular_color} colored notes</li>
                        <li>📊 <strong>Data Quality:</strong> {total_internal_links} internal + {total_external_links} external links</li>
                    </ul>
                </div>
            </div>
        </div>
        
        <!-- Word Cloud -->
        {wordcloud_section}
        
        <!-- Charts Section 1: Core Timeline Analytics -->
        <div class="row">
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-chart-line me-2"></i>Cumulative Growth</h4>
                    {timeline_chart}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-palette me-2"></i>Color Preferences</h4>
                    {colors_chart}
                </div>
            </div>
        </div>
        
        <!-- Charts Section 2: Creation Patterns (NEW!) -->
        <div class="row">
            <div class="col-12">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-calendar-alt me-2"></i>Note Creation Patterns</h4>
                    {creation_patterns_chart}
                </div>
            </div>
        </div>
        
        <!-- Charts Section 3: Activity & Momentum -->
        <div class="row">
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-fire me-2"></i>Activity Heatmap</h4>
                    {heatmap_chart}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-rocket me-2"></i>Writing Momentum</h4>
                    {momentum_chart}
                </div>
            </div>
        </div>
        
        <!-- Charts Section 4: Content Analysis -->
        <div class="row">
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-chart-bar me-2"></i>Smart Length Categories</h4>
                    {smart_word_dist_chart}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-cogs me-2"></i>Content Structure</h4>
                    {structure_chart}
                </div>
            </div>
        </div>
        
        <!-- Charts Section 5: Advanced Analytics -->
        <div class="row">
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-tachometer-alt me-2"></i>Writing Velocity Trends</h4>
                    {writing_velocity_chart}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-leaf me-2"></i>Seasonal Patterns</h4>
                    {seasonal_chart}
                </div>
            </div>
        </div>
        
        <!-- Charts Section 6: Network Analysis -->
        <div class="row">
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-network-wired me-2"></i>Knowledge Hubs</h4>
                    {top_linked_chart}
                </div>
            </div>
            <div class="col-lg-6">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-brain me-2"></i>Network Influence</h4>
                    {network_centrality_chart}
                </div>
            </div>
        </div>
        
        <!-- Detailed Stats Table -->
        <div class="row">
            <div class="col-12">
                <div class="chart-container">
                    <h4 class="mb-3"><i class="fas fa-table me-2"></i>Detailed Statistics</h4>
                    <div class="row">
                        <div class="col-md-6">
                            <h6>📊 Content Statistics</h6>
                            <ul class="list-unstyled">
                                <li><strong>Total Size:</strong> {total_size:.2f} MB</li>
                                <li><strong>Internal Links:</strong> {total_internal_links}</li>
                                <li><strong>External Links:</strong> {total_external_links}</li>
                                <li><strong>Oldest Note:</strong> {oldest_note}</li>
                                <li><strong>Newest Note:</strong> {newest_note}</li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6>🎯 Top Referenced Notes</h6>
                            <ol>
                                {top_linked_list}
                            </ol>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <footer class="bg-dark text-light py-4 mt-5">
        <div class="container text-center">
            <p>&copy; 2025 KeepVault Analytics Dashboard | Generated with ❤️ and Python</p>
        </div>
    </footer>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
        """
        
        # Prepare data for template
        stats = self.stats
        
        # Enhanced assessment of note length and patterns
        avg_words = stats['content']['avg_words_per_note']
        if avg_words < 50:
            length_assessment = "Perfect for quick notes!"
        elif avg_words < 200:
            length_assessment = "Great for detailed thoughts!"
        else:
            length_assessment = "You write comprehensive notes!"
        
        # Calculate additional advanced metrics
        notes_with_dates = [n for n in self.notes if n.created]
        if notes_with_dates:
            # Writing frequency analysis
            dates = [n.created.date() for n in notes_with_dates]
            date_range = (max(dates) - min(dates)).days
            if date_range > 0:
                notes_per_day = len(notes_with_dates) / date_range
                frequency_assessment = f"{notes_per_day:.2f} notes/day"
            else:
                frequency_assessment = "All notes created on same day"
            
            # Productivity streaks
            date_counts = Counter(dates)
            active_days = len(date_counts)
            productivity_rate = (active_days / date_range * 100) if date_range > 0 else 100
            
            # Link density
            total_links = sum(len(n.internal_links) for n in self.notes)
            if len(self.notes) > 0:
                link_density = total_links / len(self.notes)
                if link_density < 1:
                    link_assessment = "Low connectivity - consider more cross-references"
                elif link_density < 3:
                    link_assessment = "Good connectivity between notes"
                else:
                    link_assessment = "Excellent knowledge network!"
            else:
                link_assessment = "No links found"
        else:
            frequency_assessment = "No date data"
            productivity_rate = 0
            link_assessment = "No link data"
        
        # Most popular color
        if stats['colors']:
            popular_color = max(stats['colors'], key=stats['colors'].get)
        else:
            popular_color = "White"
        
        # Top linked notes list
        top_linked_list = ""
        for note, count in stats['most_linked'][:5]:
            top_linked_list += f"<li>{note} ({count} references)</li>"
        
        # Word cloud section
        wordcloud_section = ""
        if wordcloud_html:
            wordcloud_section = f"""
            <div class="row">
                <div class="col-12">
                    <div class="wordcloud-container">
                        <h4 class="mb-3"><i class="fas fa-cloud me-2"></i>Topics & Themes</h4>
                        {wordcloud_html}
                    </div>
                </div>
            </div>
            """
        
        # Fill template
        html_content = html_template.format(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_notes=stats['basic']['total_notes'],
            total_words=stats['content']['total_words'],
            avg_words=stats['content']['avg_words_per_note'],
            date_range=stats['dates']['date_range_days'],
            active_notes=stats['basic']['active_notes'],
            archived_notes=stats['basic']['archived_notes'],
            trashed_notes=stats['basic']['trashed_notes'],
            pinned_notes=stats['basic']['pinned_notes'],
            newest_date=stats['dates']['newest_date'],
            frequency_assessment=frequency_assessment,
            productivity_rate=productivity_rate,
            link_density=link_density if 'link_density' in locals() else 0,
            link_assessment=link_assessment,
            total_internal_links=stats['content']['total_internal_links'],
            total_external_links=stats['content']['total_external_links'],
            length_assessment=length_assessment,
            popular_color=popular_color.lower(),
            total_size=stats['content']['total_size_mb'],
            oldest_note=stats['dates']['oldest_note'],
            newest_note=stats['dates']['newest_note'],
            top_linked_list=top_linked_list,
            wordcloud_section=wordcloud_section,
            timeline_chart=charts.get('timeline', '<p>No timeline data available</p>'),
            colors_chart=charts.get('colors', '<p>No color data available</p>'),
            creation_patterns_chart=charts.get('creation_patterns', '<p>No creation pattern data available</p>'),
            word_dist_chart=charts.get('word_dist', '<p>No word count data available</p>'),
            smart_word_dist_chart=charts.get('smart_word_dist', '<p>No smart word distribution data available</p>'),
            heatmap_chart=charts.get('heatmap', '<p>No activity data available</p>'),
            momentum_chart=charts.get('momentum', '<p>No momentum data available</p>'),
            writing_velocity_chart=charts.get('writing_velocity', '<p>No writing velocity data available</p>'),
            structure_chart=charts.get('structure', '<p>No content structure data available</p>'),
            seasonal_chart=charts.get('seasonal', '<p>No seasonal data available</p>'),
            top_linked_chart=charts.get('top_linked', '<p>No link data available</p>'),
            network_centrality_chart=charts.get('network_centrality', '<p>No network centrality data available</p>')
        )
        
        # Write file
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"Dashboard generated: {output_path.absolute()}")
        return str(output_path.absolute())

def main():
    parser = argparse.ArgumentParser(description='Generate KeepVault Analytics Dashboard')
    parser.add_argument('--vault-path', '-v', default='../KeepVault', 
                       help='Path to KeepVault folder (default: ../KeepVault)')
    parser.add_argument('--output', '-o', default='notes_dashboard.html',
                       help='Output HTML file name (default: notes_dashboard.html)')
    
    args = parser.parse_args()
    
    # Check if vault exists
    vault_path = Path(args.vault_path)
    if not vault_path.exists():
        print(f"Error: Vault path '{vault_path}' does not exist!")
        print("Please specify correct path with --vault-path")
        sys.exit(1)
    
    print("🧠 KeepVault Analytics Dashboard Generator")
    print("=" * 50)
    
    # Initialize analyzer
    analyzer = NotesAnalyzer(vault_path)
    
    # Scan and analyze
    analyzer.scan_vault()
    
    if not analyzer.notes:
        print("No notes found in the vault!")
        sys.exit(1)
    
    # Generate dashboard
    output_file = analyzer.generate_dashboard(args.output)
    
    print(f"\n✅ Dashboard successfully generated!")
    print(f"📂 Open this file in your browser: {output_file}")
    print(f"📊 Analyzed {len(analyzer.notes)} notes")
    print(f"📝 Total words: {analyzer.stats['content']['total_words']:,}")

if __name__ == "__main__":
    main()