# Progress

## v1.1.7+ (Current)

### Web Interface & Containerization [✓]
- [x] Created Flask-based web application
- [x] Implemented RESTful API for MIDI operations
- [x] Added web-based piano roll visualization using matplotlib
- [x] Implemented browser-based MIDI playback
- [x] Created responsive web UI with Bootstrap
- [x] Added Docker containerization support
- [x] Created Docker Compose configuration
- [x] Documented web application setup and usage
- [x] Ensured cross-platform compatibility

### Recent Fixes [✓]
- [x] Fixed piano roll visualization flickering when selecting different MIDI files
- [x] Implemented file path handling to prevent duplicate paths
- [x] Added MIDI to WAV conversion with FluidSynth for browser audio playback
- [x] Implemented silence trimming for better audio playback experience
- [x] Added race condition handling for rapid UI interactions
- [x] Enhanced error handling and logging for better diagnostics
- [x] Fixed file path resolution for consistent file access across the application

### Next Steps [ ]
- [ ] Add MIDI export functionality
- [ ] Implement user accounts and saved searches
- [ ] Add more detailed MIDI analysis visualizations
- [ ] Improve MIDI playback quality in browser

## v1.1.7 (Previous)

### Audio System Improvements [✓]
- [x] Replaced pygame MIDI with FluidSynth for better sound quality
- [x] Added platform-specific audio drivers (coreaudio/dsound/alsa)
- [x] Implemented direct MIDI note playback with proper timing
- [x] Added volume control with gain adjustment
- [x] Added automatic silence trimming for MIDI files
- [x] Implemented repeat playback functionality
- [x] Improved error handling and logging for audio system

### Cross-Platform UI Consistency [✓]
- [x] Implemented universal dark theme compatible with all platforms
- [x] Added Windows-specific theme adjustments using 'clam'
- [x] Enhanced button states and visual feedback
- [x] Improved Treeview and scrollbar visibility
- [x] Standardized colors and contrast across platforms
- [x] Increased max search results from 50 to 100
---
## v1.0.0 (Previous)

### Core [✓]
- [x] MIDI feature extraction
- [x] FAISS similarity search
- [x] Feature weights system
- [x] Basic GUI

### Features [✓]
- [x] Pitch analysis (mean, std)
- [x] Duration analysis
- [x] Rhythm features (IOI, syncopation)
- [x] Interval analysis
- [x] Contour calculation

### UI [✓]
- [x] Weight sliders
- [x] File picker
- [x] Results view
- [x] Progress bar

## v1.1.0 (Previous)

### Audio [✓]
- [x] MIDI playback integration
- [x] Playback controls (play, pause, stop)
- [x] Volume control
- [x] Double-click to play results

## v1.1.1 (Previous)

### UI Enhancements [✓]
- [x] Improved layout organization
- [x] Scrollable results view
- [x] Current file display
- [x] Better visual feedback
- [x] Proper window sizing

### Error Handling [✓]
- [x] Comprehensive error catching
- [x] User-friendly error messages
- [x] Detailed logging system
- [x] Recovery from playback errors
- [x] File operation safeguards

### Code Quality [✓]
- [x] Better code organization
- [x] Enhanced documentation
- [x] Type hints throughout
- [x] Consistent error handling
- [x] Improved state management

## v1.1.2 (Previous)

### Performance [✓]
- [x] Dataset caching system
- [x] Fast startup with cached data
- [x] Cache validation
- [x] Automatic cache management
- [x] Cache directory structure
- [x] Fixed cache persistence between runs

### Bug Fixes [✓]
- [x] Fixed macOS file dialog issue
- [x] Improved error handling for missing dataset directory
- [x] Better MIDI player initialization
- [x] Graceful handling of empty dataset directory
- [x] Proper subdirectory scanning for MIDI files

## v1.1.3

### UI Improvements [✓]
- [x] Added piano roll visualization for input and selected MIDI
- [x] Dark theme with better contrast
- [x] Separate playback controls for input and selected patterns
- [x] Better organization of controls and results
- [x] Improved status feedback
- [x] Added similarity percentage display

### Piano Roll Features [✓]
- [x] Note visualization with proper timing
- [x] Time grid with markers
- [x] Note labels (C through B)
- [x] Responsive resizing
- [x] Empty bar skipping in visualization
- [x] Proper note duration display

### Known Issues [ ]
- [ ] No playback on Windows PC in GUI (works just fine on MacOS)
  (because of pygame? drivers? waiting feedback with logging details from Peiyi's tests since she has a windows pc)
- [ ] Display issues of buttons with nigth theme on Windows
- [ ] Playback Control Issues
  - Multiple files can play simultaneously when switching between input and selected patterns
  - Need to properly stop previous playback before starting new one
  - Resume function needs better state management
  - Playback controls need better visual feedback of current state
- [ ] UI Layout Issues
  - Piano roll visualizations need equal width in both panels
  - Piano roll height needs to be consistent
  - Feature weight sliders need better alignment
  - Volume control needs better visual feedback
- [ ] MIDI Processing Issues
  - Empty bars at start need more accurate detection
  - Need to handle MIDI files with no notes gracefully
  - Better tempo detection needed for some files
  - Need to handle multi-track MIDI files better
- [ ] Dataset Issues
  - Dataset path needs to exist before first run
  - Need better cache validation based on content
  - Need to handle large datasets more efficiently

### Next Steps [ ]
- [ ] Fix Playback Issues
  - Implement proper playback state management
  - Add playback position indicator
  - Add visual feedback for current playing state
  - Implement proper track selection for multi-track MIDIs
- [ ] Improve UI Layout
  - Make piano roll panels equal width
  - Add zoom controls for piano rolls
  - Add time position slider
  - Add loop points for playback
- [ ] Enhance MIDI Processing
  - Better empty bar detection
  - Improved tempo detection
  - Multi-track support
  - MIDI export functionality

## v1.1.4

### Playback Improvements [✓]
- [x] Fixed simultaneous playback issue
- [x] Implemented proper state management with PlaybackState enum
- [x] Added state change callback system
- [x] Separate tracking for input and selected files
- [x] Better visual feedback for playback state
- [x] Improved button state management
- [x] Added loop functionality for continuous playback

### UI Layout Improvements [✓]
- [x] Made piano roll panels equal width
- [x] Improved grid configuration for consistent sizing
- [x] Better organization of controls
- [x] Enhanced visual feedback
- [x] Proper expansion of piano roll displays

### Known Issues [ ]
- [ ] Search and Parameter Issues
  - No way to retry search after changing feature weights
  - Need immediate update of results when parameters change
  - Need visual feedback during parameter updates
  - Need to cache search results for quick parameter adjustments
- [ ] UI Layout Issues
  - Some elements still need better alignment
  - Need more consistent spacing between elements
  - Status bar could use better organization
- [ ] MIDI Processing Issues
  - Empty bars at start need more accurate detection
  - Need to handle MIDI files with no notes gracefully
  - Better tempo detection needed for some files
  - Need to handle multi-track MIDI files better

### Next Steps [ ]
- [ ] Implement Search Parameter Updates
  - Add immediate search update on parameter change
  - Add progress indicator for parameter updates
  - Implement result caching for quick updates
  - Add reset button for parameters
- [ ] Further UI Improvements
  - Add more visual feedback for parameter changes
  - Improve status bar organization
  - Add tooltips for controls
  - Better spacing and alignment
- [ ] Enhance MIDI Processing
  - Better empty bar detection
  - Improved tempo detection
  - Multi-track support
  - MIDI export functionality

## v1.1.5

### Search Parameter Improvements [✓]
- [x] Added "Search Again" button for manual search updates
- [x] Removed automatic search on parameter changes
- [x] Better user feedback during search operations
- [x] Improved error handling for search operations
- [x] Clear visual feedback with styled search button

### Known Issues [ ]
- [ ] UI Layout Issues
  - Some elements still need better alignment
  - Need more consistent spacing between elements
  - Status bar could use better organization
- [ ] Piano Roll Visualization Issues
  - Note lines need to be thicker and more visible
  - Notes sometimes not visible due to pitch range differences
  - Need pitch normalization for better comparison
  - Grid lines could be more subtle to emphasize notes
  - Need better visual distinction between input and selected patterns
  - Time scale needs better readability
- [ ] MIDI Processing Issues
  - Empty bars at start need more accurate detection
  - Need to handle MIDI files with no notes gracefully
  - Better tempo detection needed for some files
  - Need to handle multi-track MIDI files better

### Next Steps [ ]
- [ ] Improve Piano Roll Visualization
  - Implement pitch range normalization
  - Increase note line thickness
  - Add color intensity based on velocity
  - Add zoom controls for detailed view
  - Improve grid line visibility
  - Add note labels on hover
  - Add time markers for better navigation
- [ ] Further UI Improvements
  - Add more visual feedback for parameter changes
  - Improve status bar organization
  - Add tooltips for controls
  - Better spacing and alignment
- [ ] Enhance MIDI Processing
  - Better empty bar detection
  - Improved tempo detection
  - Multi-track support
  - MIDI export functionality

## v1.1.6

### Piano Roll Visualization Improvements [✓]
- [x] Fixed note visibility with bright green color
- [x] Added proper error handling for MIDI visualization
- [x] Implemented pitch range normalization
- [x] Added highlight effect for better note visibility
- [x] Fixed note label creation issues
- [x] Improved grid line visibility
- [x] Added recovery mechanisms for visualization errors
- [x] Made piano roll panels equal width
- [x] Removed bold formatting from note labels
- [x] Synchronized time scales between input and selected patterns
- [x] Improved vertical space utilization
- [x] Fixed alignment of piano roll headers

### UI Theme Improvements [✓]
- [x] Implemented universal dark theme compatible with all platforms
- [x] Enhanced contrast for better visibility
- [x] Added consistent accent colors for playback controls
- [x] Improved button visibility on Windows
- [x] Standardized color scheme across all UI elements
- [x] Refined text colors for better readability
- [x] Added explicit hover and pressed states for buttons
- [x] Enhanced selection highlighting in Treeview
- [x] Standardized border widths and relief styles
- [x] Improved scroll bar visibility with arrow colors
  (couldn't check properly on windows yet though)

### Dataset Integration [✓]
- [x] Added clear dataset path requirements
- [x] Specified Lakh_MIDI_Clean_Patterns_v1 as current dataset
- [x] Added dataset download link for UiT users
- [x] Updated documentation with dataset setup instructions
- [x] Added dataset structure validation checks

### Known Issues [ ]
- [ ] Dataset Management Issues
  - Need better error messages for missing dataset directory
  - Need automated dataset structure validation
  - Need better handling of dataset loading errors
  - Need progress indicator for initial dataset processing
  - Need better caching system for processed dataset
- [ ] Playback Issues
  - Error updating playback state with invalid command name
  - Need better cleanup of playback resources
  - Playback controls could use better state synchronization
- [ ] Piano Roll Fine-tuning Needed
  - Could use velocity-based note coloring
  - Need zoom controls for detailed view
  - Time markers could be more informative
  - Grid lines could be more subtle
- [ ] UI Layout Issues
  - Status bar needs better organization
  - Need tooltips for controls and features
  - Volume control needs better visual feedback

### Next Steps [ ]
- [ ] Improve Dataset Management
  - Add automated dataset directory creation
  - Add dataset structure validation
  - Add dataset processing progress indicators
  - Improve error messages for dataset issues
  - Add dataset statistics view
- [ ] Fix Playback Issues
  - Implement proper playback state cleanup
  - Add better error handling for playback controls
  - Improve state synchronization between controls
- [ ] Enhance Piano Roll Features
  - Add velocity-based note coloring
  - Implement zoom controls
  - Add more informative time markers
  - Fine-tune grid line appearance
- [ ] Polish UI
  - Reorganize status bar
  - Add tooltips
  - Improve volume control feedback
  - Add keyboard shortcuts for common actions


### Known Issues [ ]
- [ ] FluidSynth Setup
  - [x] Added FluidR3_GM.sf2 soundfont to application
  - [ ] Need to handle soundfont loading errors gracefully
  - [ ] Need to test FluidSynth on different Windows versions
- [ ] UI Fine-tuning
  - Some elements might need size adjustments on Windows
  - Need to test high DPI displays
  - Font rendering differences between platforms
- [ ] Playback Features
  - Need to add visual feedback for repeat mode
  - Need to add repeat toggle control in UI
  - Consider adding loop point selection

### Next Steps [ ]
- [ ] Enhance Playback Controls
  - Add repeat mode toggle button
  - Add visual indicator for repeat status
  - Add loop point selection interface
- [ ] UI Polish
  - Add more visual feedback for playback state
  - Fine-tune element sizes for Windows
  - Test and adjust for various display configurations
- [ ] Documentation
  - Update user guide with new FluidSynth features
  - Add troubleshooting section for audio setup
  - Document platform-specific considerations

## Unit Testing Priority [ ]
- [ ] Core Feature Extraction & Analysis
  - Port existing tests from Clustering_repeated_motifs_v040_clean.ipynb
  - Expand test coverage for feature calculation
  - Add tests for similarity search algorithms
  - Test edge cases in MIDI processing
- [ ] Database & Caching
  - Test dataset loading and processing
  - Verify cache functionality
  - Test search result accuracy
  - Add performance benchmarks
- [ ] Audio System
  - Test FluidSynth integration
  - Verify playback state management
  - Test audio driver compatibility
  - Add stress tests for concurrent playback
- [ ] UI Components
  - Test piano roll rendering
  - Verify user input handling
  - Test state management
  - Add integration tests for UI flows

### Testing Goals
- Achieve 95%+ test coverage
- Implement continuous integration
- Establish automated test pipeline
- Regular benchmark testing
- Regression test suite

## Planned Versions
- v1.1.7: Piano Roll Fine-tuning
  - Equal time scaling
  - Velocity-based coloring
  - Label and grid refinements
  - Interactive features

- v1.2.0: Advanced Playback Features
  - Add playback position indicator
  - Add time position slider
  - Add loop points
  - Add track selection for multi-track MIDIs

- v1.3.0: Enhanced MIDI Processing
  - Better multi-track support
  - Advanced tempo detection
  - MIDI modification and export
  - Loop point support

- v1.4.0: Advanced Features
  - Dataset management tools
  - Advanced visualization options
  - Batch processing capabilities
  - Plugin system for extensions

## Logging & Investigation
- Integrated logging across all modules (including midi_player.py, feature_calculator.py, database.py, etc.) for diagnostics and troubleshooting.
- Detailed logs capture events, errors, and state changes, which are being used to investigate issues such as MIDI playback problems on Windows PCs.
