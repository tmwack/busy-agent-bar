#!/bin/sh
# agentbar plugin: the time, and a line along the bottom that fills as the hour passes.
# Use it with:  [plugin]  command = "/path/to/examples/clock.sh"  interval_s = 30
time=$(date +%-H:%M)
minute=$(date +%-M)
fill=$(( minute * 16 / 60 + 1 ))   # 1-16 columns
printf '{"elements": [
  {"type": "text", "x": 0, "y": 3, "text": "%s", "font": "small", "color": "#909090"},
  {"type": "rectangle", "x": 0, "y": 14, "width": %d, "height": 1, "fill_colors": ["#385868"]}
]}\n' "$time" "$fill"
