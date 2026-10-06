𝐃𝐨 𝐲𝐨𝐮 𝐰𝐚𝐧𝐭 𝐭𝐨 𝐤𝐧𝐨𝐰 𝐰𝐡𝐞𝐫𝐞 𝐈 𝐰𝐚𝐥𝐤 𝐝𝐮𝐫𝐢𝐧𝐠 𝐥𝐮𝐧𝐜𝐡?

I've always wanted to have a tool to display all my activity tracks from 𝐆𝐚𝐫𝐦𝐢𝐧 on a global map. Which allows zooming and panning, selecting different time spans, etc. So, I created it in June. A minimal viable prototype was quickly done. Issues with broken tracks (GPX and the jitters ..) were fixed, and some optimizations to the loading and caching of the 𝐎𝐩𝐞𝐧𝐒𝐭𝐫𝐞𝐞𝐭𝐌𝐚𝐩 tiles were also done.  
But then the 𝐬𝐡𝐨𝐰𝐬𝐭𝐨𝐩𝐩𝐞𝐫: it does not scale! I had used some hundred exported tracks initially: loads quite fast and also the mapping to the global coordinates was done within milliseconds. But when I tried to load all of the almost 10k tracks (I have been doing this for almost a decade ..), the app froze!  

A classic in software development: it does not scale. What now?  

Quite simple: profile a run, determine the bottlenecks and optimize. Of course, part of that can be done in an agentic way. Urging the agents to pre-process all tracks and store them in a more suitable format (QPainterPath) for quick lookup got us halfway there.

So here is version 0.0110 of 𝐆𝐚𝐫𝐦𝐢𝐧𝐀𝐜𝐭𝐢𝐯𝐢𝐭𝐲𝐌𝐚𝐩 (quite an uncreative name ..) - a 𝐏𝐲𝐐𝐭 𝟔.𝟏𝟏 app, with Python 3.14, 11k LoC (4k for the functionality and the rest for tooling & tests), 𝟗𝟖% 𝐜𝐨𝐯𝐞𝐫𝐚𝐠𝐞, local and GitHub Actions pipelines, .. you know the drill. You also receive a nice shell script to export your data from Garmin (if you don't want to request a GDPR export and wait some days).  
𝐅𝐮𝐥𝐥𝐲 𝐥𝐨𝐜𝐚𝐥, nothing is sent to the cloud or leaves your computer.

It really stands on the shoulders of giants: big thanks to the people behind OpenStreetMap and all the frameworks used. It would not be possible to create such a custom project without their work.

PS. to resolve the headline: those are the streets adjacent to the @DataModul headquarter in Munich/Laim.
