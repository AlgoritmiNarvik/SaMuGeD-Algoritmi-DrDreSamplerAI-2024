## 2026-10-05: reduce full song animation work

Full song scenes previously visited every displayed event on each playback frame. They now keep the complete source drawing static and animate only events in the selected loop and audible source parts. Initial note and drum tail opacity stays the same. Offscreen views already skip animation updates.

A local Schism benchmark reduced visited events from 3400 to 78. With DOM writes stubbed, median JavaScript time per frame across ten batches of 600 frames fell from 0.70 ms to 0.034 ms. This measures update logic, not browser painting, scrolling FPS or total page performance.

All 35 transport and animation tests pass. The new test checks loop boundaries, contextual instruments and drum inclusion. Source notes, occurrence bands, audio and navigation remain unchanged.

The machine snapshot showed 11 GiB available disk space, 18 logical CPUs, load averages near 4 and active Chrome and WindowServer processes. This does not establish the cause of observed scrolling delays. The local guitar comparison page uses native audio controls and has no note animation loop.
