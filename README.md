Moodle/EEG Synchronization Prototype

A prototype system for synchronizing behavioral data from a Moodle LMS with physiological (EEG) data from a wearable in-ear device, producing a unified chronological timeline for cognitive load research. Developed as a SUPSI (Scuola universitaria professionale della Svizzera italiana) Bachelor diploma project in Computer Science.

Unlike prior art in this space (e.g. GOAL, M2LADS), this system integrates natively with Moodle's Events API rather than relying on external browser trackers or logging proxies.

## Overview
 
The project is composed of three independent components, each in its own repository, that together form a data-collection pipeline:
 
| Component | Role | Sends to |
|---|---|---|
| `moodle-plugin` | Captures behavioral events (clicks, quiz attempts, navigation, video, drag-and-drop) | `backend` via `POST /api/v1/events` |
| `eeg-visualizer` | Streams EEG data (250 Hz), computes band powers, monitors clock synchronization | `backend` via `POST /api/v1/events` |
| `backend` | Ingests events from both sources and stores them as a single append-only chronological log | — |
 
Each repository can be developed, tested, and deployed independently; they are joined only by the JSON event contract they exchange with the backend.

## Repositories

### 1. `moodle-plugin`
Moodle plugin that captures behavioral events during a learning session (clicks, quiz attempts, navigation, video, drag-and-drop) and forwards them to the backend.

### 2. `eeg-visualizer`
Desktop application that streams and processes EEG data in real time from the IDUN Guardian 3 device, computes band powers, monitors clock synchronization, and uploads the data to the backend.

### 3. `backend`
Backend service that receives events from the other two components and stores them as a single append-only chronological log.

## Data Flow

1. A learner interacts with a Moodle course; `moodle-plugin` observes and forwards behavioral events.
2. `eeg-visualizer` streams EEG data from the IDUN Guardian 3 concurrently, computing band powers and monitoring clock skew.
3. Both components POST their events to the backend's `/api/v1/events` endpoint.
4. The backend timestamp-normalizes and stores everything as a single ordered timeline, ready for offline temporal correlation and cognitive-load analysis.

## Getting Started

Each folder has its own setup instructions — see the README inside each subfolder for environment setup, dependencies, and run instructions:

- `moodle-plugin/README.md`
- `eeg-visualizer/README.md`
- `backend/README.md`

## Project Context

This system was built to study physiological correlates of cognitive load during Moodle-based learning activities (arithmetic tasks, n-back tasks). EEG bands are treated as indicators/correlates of cognitive load, not as direct measures.

- **Supervisors:** Vanini Salvatore (relatore), Sommaruga Lorenzo (correlatore)
- **Institution:** SUPSI — Scuola universitaria professionale della Svizzera italiana
- **Part of the European project:** UPRAISE

## License

**© 2026 Andrea Perlini. All rights reserved.**
 
This project is confidential and part of a diploma thesis (SUPSI, project C11326). No part of this repository may be used, copied, modified, or redistributed without prior written permission from the author.
