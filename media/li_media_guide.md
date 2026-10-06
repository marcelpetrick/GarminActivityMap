# LinkedIn media guide

Findings for posting short screen recordings (such as the activity map replay)
on LinkedIn. The limits come from third-party guides, checked on 2026-10-06, not
from official LinkedIn documentation, so treat them as reported behaviour.

## Which format to use

| Goal | Format | Why |
|---|---|---|
| Sharpest image, safest upload | MP4 (H.264) | Recommended format for native video |
| Endless loop in the feed | Animated GIF | Loops forever, within the limits below |
| Already have one | WebM | Accepted, but MP4 is the safer choice |

## Native video (post button: video)

- **Formats:** MP4 recommended. MOV, AVI, WMV, FLV, ASF, MPEG-1, MPEG-4, MKV and WebM are also accepted.
- **Codec:** H.264 is the safest choice. Use `yuv420p`, even width and height, and `-movflags +faststart`.
- **File size:** up to 5 GB for organic posts. Video ads are MP4 only, up to 200 MB.
- **Duration:** at least 3 seconds. At most 15 minutes from desktop, 10 minutes from mobile.
- **Playback:** videos autoplay muted in the feed. Videos under 30 s loop only until about 30 s of total playtime, so a 14 s clip plays about twice and then stops.
- **Aspect ratio:** square (1:1, e.g. 1080×1080) works well in the feed. Landscape 16:9 is 1920×1080.

## Animated GIF (post button: photo)

- **How to upload:** use the **photo** button, not the video button. Otherwise the GIF is converted and stops looping.
- **Size:** reportedly at most 5 MB. Aim for under 3 MB so it loads quickly.
- **Frames:** reportedly fewer than 400. Above 5 MB or 400 frames, LinkedIn freezes the GIF on its first frame.
- **Frame rate:** frames ≤ 399 means fps ≤ 399 / clip length. For a 14 s clip that is at most 28 fps, so use 20 or 25 fps. GIF timing works in steps of 1/100 s, so 10, 20, 25 or 50 fps keep the timing exact.
- **Looping:** export with an infinite loop (`-loop 0` in ffmpeg).
- **Quality:** GIF is limited to 256 colours per frame and has no modern compression. Expect less sharp text and possible dithering compared to MP4.

## Measured: lunchbreaks2026 clip

Source: `Screencast_20261006_221518.webm` (VP9, 1200×1200, variable frame rate
of about 52–59 fps, 46 s). The clip runs from 0:32 to the end (14.0 s). Every
version was scored against a lossless cut with ffmpeg's SSIM and VMAF filters.
A perfect copy scores VMAF 97.4, which is the ceiling here.

| File | Size | Format | fps | VMAF | SSIM | Use |
|---|---:|---|---:|---:|---:|---|
| `lunchbreaks2026.mp4` | 373 KiB | H.264 High@4.1, CRF 26, tune animation | 30 | 95.6 | 0.991 | **Post this.** Smallest near-lossless file, safest for LinkedIn |
| `lunchbreaks2026_maxquality.mp4` | 1.2 MiB | H.264, CRF 16 | 30 | 97.1 | 0.998 | Visually lossless |
| `lunchbreaks2026.webm` | 493 KiB | VP9 two-pass, CRF 40 | 30 | 95.9 | 0.993 | WebM as requested |
| `lunchbreaks2026_maxquality.webm` | 722 KiB | VP9 two-pass, CRF 24 | 30 | 96.7 | 0.995 | Higher-quality WebM |
| `lunchbreaks2026.gif` | 4.49 MiB (4.71 MB) | 56 colours, no dither, 140 frames | 10 | 87.5 | 0.987 | Endless loop, best GIF under 5 MB |
| `lunchbreaks2026_small.gif` | 2.21 MiB | 24 colours, no dither, 140 frames | 10 | 85.4 | 0.976 | Endless loop, under 3 MB |

All files are 1200×1200, have no audio and start cleanly on the first replay frame.

What the comparison showed:

- **30 fps is enough.** 60 fps made files 50–100% bigger for about +0.3 VMAF.
- **Keep the native 1200×1200.** Scaling to 1080×1080 was not smaller at the same quality and softened the small panel text.
- **H.264:** `-tune animation` saves 10–13% compared with no tune. `-tune stillimage` costs 20% more. `-level:v 4.1` gives a widely supported stream for about 1 KiB extra.
- **VP9:** `-tune-content screen` and `-aq-mode` had no effect. From CRF 48 upwards, small digits start to blur.
- **A lossless stream copy is not possible.** The source keyframes sit at 29.99 s and 32.22 s, so `-c copy` starts 2 s early on the finished previous replay.
- **GIF:** fewer colours at native resolution beat downscaling. With no dither, `stats_mode=full` and `diff_mode=rectangle`, the files were smallest and showed no banding. With 24 colours, the opacity slider turns pink and the text gets a slight blue tint.
- **GIF compared with video:** even a 256-colour GIF needs 8.4 MB to reach VMAF 93.7. Video gives far better quality per byte, and GIF is only worth it for the endless loop.

Commands (from the lossless cut `reference.mkv`; replace the input with
`-ss 32 -i Screencast_20261006_221518.webm` to work from the original):

```bash
# Lossless reference cut
ffmpeg -ss 32 -i Screencast_20261006_221518.webm -map 0:v -c:v ffv1 -level 3 -fps_mode passthrough reference.mkv

# lunchbreaks2026.mp4
ffmpeg -i reference.mkv -an -vf "fps=30,format=yuv420p" -c:v libx264 -preset veryslow -crf 26 \
  -tune animation -profile:v high -level:v 4.1 -pix_fmt yuv420p -movflags +faststart lunchbreaks2026.mp4

# lunchbreaks2026.webm (two passes)
ffmpeg -i reference.mkv -an -vf fps=30 -pix_fmt yuv420p -c:v libvpx-vp9 -b:v 0 -crf 40 \
  -deadline good -cpu-used 0 -row-mt 1 -tile-columns 2 -g 240 -pass 1 -f null /dev/null
ffmpeg -i reference.mkv -an -vf fps=30 -pix_fmt yuv420p -c:v libvpx-vp9 -b:v 0 -crf 40 \
  -deadline good -cpu-used 0 -row-mt 1 -tile-columns 2 -g 240 -pass 2 lunchbreaks2026.webm

# lunchbreaks2026.gif (max_colors=24 for the small version)
ffmpeg -i reference.mkv -filter_complex "fps=10,scale=1200:1200:flags=lanczos,split[a][b];\
[a]palettegen=max_colors=56:stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 lunchbreaks2026.gif
```

## Checklist before posting

1. Cut the clip so it starts cleanly. Check the first frame, because it is the GIF fallback and the video thumbnail.
2. MP4: H.264, `yuv420p`, constant frame rate, `+faststart`, at least 3 s.
3. GIF: under 5 MB (ideally under 3 MB), under 400 frames, `loop=0`, uploaded as a photo.
4. Keep small UI text readable: prefer the native resolution or 1080×1080 over heavy downscaling.
5. Privacy: map recordings show real places. Check that no home or work location is identifiable before posting.

## Sources

- [LinkedIn Video Specs 2026 (Sendspark)](https://blog.sendspark.com/linkedin-video-specs)
- [LinkedIn Video Specs 2026 (Yans Media)](https://www.yansmedia.com/blog/linkedin-video-specs)
- [How to Post a GIF on LinkedIn (+ Size Limits & Fixes) (AuthoredUp)](https://authoredup.com/blog/how-to-post-a-gif-to-linkedin)
- [How to Post GIFs on LinkedIn in 2026 (ConnectSafely)](https://connectsafely.ai/articles/how-to-post-gifs-on-linkedin-2026)
- [Can You Use GIFs on LinkedIn? (2PR.IO)](https://2pr.io/blog/can-you-do-gifs-on-linkedin)
