---
title: "Introducing SpeechCraft Studio"
date: 2026-09-04
author: Tracy Smith
category: Projects
---

# SpeechCraft Studio

When I was working at ShazaCin Accessible Media on the audio description app describeAT, I was already deep into sound editing and developing a new interest in AI. What I didn't expect was how those threads would eventually weave together into something entirely different.

SpeechCraft Studio began as an accident — or rather, as an experiment that got out of hand in the best possible way.

## The Burrow

I thought I'd build something simple to help me clean out loud breaths from audio. It's a time-consuming job, and I figured AI could automate part of it. After watching the first breath-smoothing version work, I realised the possibilities were much bigger than I'd imagined. I just had to say "I wonder if I could …" and keep going.

SpeechCraft Studio is a bit like the Burrow from Harry Potter — one room built on top of another, each addition sparking the next.

## The rooms in the house

**Room one: breath smoothing.** The original idea. RMS-based detection that finds breaths and attenuates them automatically.

**Room two: transcription.** Once I had the basics of an editor, I wanted something like Descript — where you edit audio the way you'd edit text. If I said "um," I could just delete the word. So I added transcription.

**Room three: line placement.** If there's a transcript, I thought, can't I automate where audio description lines go? Anyone who's placed AD lines knows the hours of work it takes to get them in the right place. So I built a line placer system — import your script file, and it matches against the transcript to position the lines automatically.

**Room four: studio recording.** From there came the studio recorder. Two people — the voice artist and the director — see the same script. As recording happens, SpeechCraft Studio places the lines in real time. You can say "oops" or hit redo if you make a mistake.

I also built in Braille display support so the next line pops up automatically, and a way to connect two monitors (or a second laptop over the network) so both director and voice artist can see what they're reading.

**The additions kept coming.** Text-to-speech for when you want an AI voice at any stage. Effects — compressor, de-esser, EQ, noise gate, normaliser, room tone match — because I don't always have the budget for expensive audio plugins. A bug reporter that pre-fills GitHub issues for you. And, of course, all of it designed to work with NVDA, JAWS, and other screen readers.

## The making of it

This project took months of work — contrary to the belief that you just say the word and an app appears. It took a lot of testing, learning, and retrying. Sometimes I got frustrated. Sometimes I broke something that previously worked. I ran into walls where I didn't know how to make the app behave the way I wanted it to.

But despite those moments, I had tremendous fun. And the feeling I get when something finally works is the same happiness and pride I feel when I wear a sweater I've made myself.

In the months between starting SpeechCraft Studio and today, I've learned a lot about building with AI. Combined with my short time working as an apprentice with an experienced app developer at BGC, the way I work now is not the way I worked at the beginning. The journey itself was part of the reward.

## Try it

SpeechCraft Studio is a free, open-source desktop audio editor for Windows. It's natively accessible for screen reader users, and it's available as a single `.exe` file — no installer needed.

- **Download:** https://github.com/trasles16-ux/speechcraft-audio/releases
- **Source code:** https://github.com/trasles16-ux/speechcraft-audio (MIT license)
- **Bug reports / feature requests:** https://github.com/trasles16-ux/speechcraft-audio/issues

I'd love to hear what you think. Send me any feature requests or let me know if you find a bug. And if you'd like to contribute, the repo is open to pull requests.

I hope you enjoy making audio.

— Tracy
