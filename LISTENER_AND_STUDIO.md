# Listener experience and operator studio

- Listener: http://127.0.0.1:5097/
- Operator: http://127.0.0.1:5097/studio

The listener sees podcast cards and a persistent player: play/pause, seeking, skip fifteen seconds, volume and playback speed from 0.85 to 1.0. No advertiser inventories, profiles, prompt controls, generation logs or voice permissions appear on this page. The completed gym-ad edition is the initial prepared version of the Philosophy of Success episode.

Studio retains podcast upload and Kaggle analysis, advertiser briefs, profile exclusions, contextual matching, parallel agent teams, voice permissions, and internal playback/review. Opening the page does not trigger paid generation. A prepared stock-voice session can be published with **Publish to listeners**. This exports one continuous episode in the background; the prior listening edition stays available until the new export succeeds. Reloading the listener page loads the latest published edition. An already-playing audio stream keeps its current edition.

The Studio workflow strip explains analysis → matching → creation/review → delivery. A collapsed demo highlight plays the approved confidence/progress/gym example. Technical setup stays within the operator page.

Custom voices remain in permission-scoped live playback; public downloadable exports of custom voice sessions are blocked. The current separation is for a localhost demo, not authenticated multi-user administration or production hosting.

Delivery state and generated editions live in the ignored `cache/live/listener` folder, with export logs and stage timings. Tests exercise an actual synthetic-audio export and verify unfinished, empty, and custom-voice sessions cannot be published. Existing upload and scoped-media HTTP checks pass.
