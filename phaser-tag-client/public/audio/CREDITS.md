# Audio credits

## Chillin mood: "Lofi Hip Hop Loop"

| | |
|---|---|
| Title | Lofi Hip Hop Loop |
| Author | omfgdude (OpenGameArt user; also credits as "OMF-Games"; the file's ARTIST tag reads "Taylor Harris") |
| Source | https://opengameart.org/content/lofi-hip-hop-loop (node 94031) |
| Original file | https://opengameart.org/sites/default/files/LofiLoop_2.ogg (served as `LofiLoop.ogg`, 1.4 MB, 2:08, Vorbis mono 22.05 kHz ~89 kbps) |
| License | **CC0 1.0 Universal (public domain dedication)**: https://creativecommons.org/publicdomain/zero/1.0/ |
| Checked | 2026-10-06. The page's "License(s)" field shows CC0 and links to the CC0 1.0 deed. In the comments the author says "I specifically do not need attribution for this". |

The description says it was "inspired by juhani junkala's level 3",
which links to https://opengameart.org/content/5-chiptunes-action
("5 Chiptunes (Action)" by SubspaceAudio / Juhani Junkala). That pack is
also CC0 1.0.

Files here:

- `lofi-hip-hop-loop.ogg`: the original download, unmodified
  (sha256 `e57ba821d4db8d66783ca984a2778ec68d1439e862239ec36407344ef3bd1eab`).
- `lofi-hip-hop-loop.mp3`: an MP3 transcode for browsers without Ogg
  Vorbis support (older Safari / iOS). Made with
  `ffmpeg -i lofi-hip-hop-loop.ogg -codec:a libmp3lame -b:a 96k -ac 1 lofi-hip-hop-loop.mp3`.

CC0 doesn't require attribution. We credit the author here anyway.

All other music and sound effects are synthesised at runtime by
`src/audio.ts`. No other audio assets are used.
