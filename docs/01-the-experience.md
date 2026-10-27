---
layout: article
title: "Part 1 — The Experience"
description: "AI Can Build Fast. Keeping Agents Aligned Is the Hard Part."
permalink: /the-experience/
author: Mike Meyers
date: 2026-10-22
redirect_from: /introduction/
---

# Part 1 — The Experience

## AI Can Build Fast. Keeping Agents Aligned Is the Hard Part.

AI agents are powerful tools. Using them, you can assemble a team capable of building your software project. One agent can help with product design, another with development, and another with testing. They don't even need to work simultaneously. You can coordinate them yourself, assigning work as you go.

After a career in software development, the first time I worked this way, my mind was blown.

You ask Claude to build something, watch it work for a bit, and then, bam, there it is. Done. Nothing short of amazing!

But then you start using what it built.

This needs a tweak. That's not quite right. Something over here was never discussed and needs to go away. But something over there is a feature you never thought of, and that's a keeper.

So, you keep working. You introduce another agent, perhaps ChatGPT, to help with product design and requirements. Now the instructions are better, the implementations improve, and you're making real progress.

Eventually, you bring in a testing agent, maybe Codex, to find bugs and things you've missed.

And it works! The agents are designing, building, testing, and fixing software at an incredible pace.

But something else is happening.

***AI doesn't just accelerate development. It also accelerates the rate at which your project accumulates decisions, assumptions, changes, and unfinished work.***
{: .pull-quote}

And someone has to keep track of all that.

### When things start to drift

At one point in my own project, I noticed that relatively small bug fixes were taking longer and longer.

Claude had accumulated a growing collection of end-to-end tests, largely in response to issues identified by my QA agent. Every time it made a change, it wanted to run all those tests.

So, naturally, I asked Claude to improve the testing process and make it faster.

Testing isn't exactly my favorite part of software development, so I was happy to let Claude work on it. I was pretty much on autopilot, and I could see the activity indicator churning away.

But after a couple of extremely long testing periods, I started wondering what was going on. Why was this taking so long? Was I getting throttled?

Turns out, Claude was building a full-blown, professional-grade testing harness. Something that could probably compete with products already on the market.

I didn't need a testing product. I needed to test my product!

The funny thing is, Claude hadn't really done anything wrong. I'd given it an underspecified goal, and it was pursuing what it considered a reasonable solution.

I'd like to think I could simply write a better prompt next time. But we're still human, after all. Details get missed, especially as projects grow. Better prompts help. So does reviewing what agents are doing along the way. But…

***Once you've made a decision, you shouldn't have to remember to repeat it every time a new agent starts working.***
{: .pull-quote}

Spoiler alert. We won’t remember.

### From developer to conductor

I don't know if there's an official name for working this way. I just call it multi-agent development.

And I think it's a powerful way to build software. A single developer can accomplish things that would have required a much larger team not long ago.

But your role changes.

You're not necessarily writing the code anymore. You're more like a product owner and conductor, with each agent playing a different part in the orchestra.

And just like a real orchestra, everyone needs to understand more than their individual part. They need to know how their work fits into the whole.

Now imagine the musicians keep coming and going.

That's essentially what happens with AI agents. Sessions reach their limits. New sessions begin. Different agents join at different stages of the project. Meanwhile, decisions get made, assumptions change, and features evolve. Keeping everyone working from the same understanding becomes a real job.

That's the problem that eventually led me to build **Charter**, a small, free tool for managing the decisions that govern a software project across AI agents and sessions.

But before getting into the tool itself, it's worth understanding the problem a little more closely.
