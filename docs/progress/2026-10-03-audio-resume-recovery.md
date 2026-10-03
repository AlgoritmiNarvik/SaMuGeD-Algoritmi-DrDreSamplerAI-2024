## 2026-10-03: recover playback after browser audio pauses

Both players now distinguish an active loop from a suspended or interrupted audio context. Pressing Play resumes a browser paused loop rather than treating it as a Stop request. A state change updates the button and status so playback is not reported as active while the browser pauses its audio context. A closed context is recreated on the next request. The output sample rate follows the browser device while source files remain 48 kHz.

Eighteen audio transport checks passed, including four new suspended and interrupted recovery cases. Twenty Space and analytics checks passed. Browser startup and track replacement were checked on both listening pages. The reported silence was not reproduced in the available Chrome session, so the affected device still needs confirmation.
