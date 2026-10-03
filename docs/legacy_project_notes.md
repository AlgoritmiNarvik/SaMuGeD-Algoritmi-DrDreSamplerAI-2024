# SaMuGeD-24 MIDI sampling notes

This page is an archival planning note from the early SaMuGeD project. It records the ideas and setup that existed at that time. It does not describe the current audited recurrence dataset or its publication status. See the [current research guide](research/README.md) and [publication status](research/DELIVERY.md).

## Historical to-do list

### Refine pattern recognition

Focus on identifying and clustering repetitive musical phrases.
Experiment with MIDI toolkit to get time signatures and divide notes into bars.

### SF segmenter enhancements

Adjust parameters for better segmentation of smaller parts.
Develop a user-friendly interface for parameter adjustments.

### Clustering approach

Use histograms to analyze note frequencies within bars.
Explore clustering algorithms to identify repetitive patterns.

### User input and flexibility

Allow users to experiment with different segment lengths and configurations.
Consider user settings for tolerable silence durations in samples.

## Historical roadmap

![Roadmap for SaMuGeD](/docs/Roadmap_for_SaMuGeD.png) 

## Setup
### Create and start a virtual environment
#### Windows
```sh
python -m venv .venv
.\.venv\Scripts\activate
```

#### Unix (Linux, macOS)
```sh
python3 -m venv .venv
source .venv/bin/activate
```

### Install required packages
For all systems, use the following command to install all required packages:
```sh
pip install -r requirements.txt
```
For Unix-based systems (e.g., Linux, macOS), use the command below to install all necessary dependencies:
```sh
pip install -r requirements_unix.txt
```

## Inspiration

[![Watch the video](https://img.youtube.com/vi/eiknHyeNCpY/0.jpg)](https://www.youtube.com/watch?v=eiknHyeNCpY)
