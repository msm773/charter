---
layout: article
title: "AI Can Build Fast. Keeping Agents Aligned Is the Hard Part."
description: "Introduction to a series on context management for multi-agent development"
permalink: /introduction/
---

# AI Can Build Fast. Keeping Agents Aligned Is the Hard Part.

*Charter — Introduction to a series on context management for multi-agent development*

AI agents are powerful tools. Using them, you can assemble a team capable of building your software project. Each agent can take on a different role: product designer, software developer, quality assurance engineer, and so on. In my opinion, this is one of the biggest opportunities for software development today.

And you don't need a sophisticated orchestration system or a team of agents all running at once. You can simply work with different agents for different purposes, coordinating their work yourself.

When you first start building this way, especially after a career in software development, your mind is blown.

You ask Claude to build something, watch it work for a bit, and then, bam, there it is. Done. Nothing short of amazing!

But then you start using what it built.

This needs a tweak. That's not quite right. Something over here was never discussed and needs to go away. But something over there is a feature you never thought of, and that's a keeper.

As you dig around, you start noticing other things. Strange wording, labels that technically make sense but aren't what you'd expect to see, workflows that aren't quite right. So you ask Claude to fix them, and it does. But the more you look, the more you find.

Before long, you realize that building even a moderately complex system is going to take some work. It's not just two hours of magic and you're done.

Still impressive, absolutely. But some of that initial shine starts to wear off.

Eventually, you discover that using another agent, perhaps one that's particularly good at language and product definition, like ChatGPT, can make a big difference. You start working through product requirements and design decisions with one agent, then handing the work off to another to implement.

Now things really start moving. Features are better defined, the initial implementations are better, and you're spending less time fixing things that weren't quite what you had in mind.

Then, as you get closer to releasing your product, you start demonstrating it to others. And, of course, you find bugs. Lots of them.

Fortunately, agents are pretty good at fixing bugs. And that gives you another idea: why not have an agent dedicated to testing?

So maybe you fire up Codex and put it to work as your QA engineer. It starts finding bugs, abandoned code, UI issues, API problems, and things you hadn't even thought to test.

Great! Except now there's even more work to do.

And this is where something starts to become apparent.

**AI doesn't just accelerate development. It also accelerates the rate at which your project accumulates decisions, assumptions, changes, and unfinished work.**

All of that progress is real. But so is the growing amount of work involved in keeping everything coordinated.

## When things start to drift

At some point in my own project, I noticed that seemingly small bug fixes were taking longer and longer.

Claude had accumulated a growing collection of end-to-end tests, largely in response to issues identified during QA. Every time it made a change, it wanted to run all these tests.

So, naturally, I asked Claude to improve the testing process and make it faster.

Testing isn't exactly the most exciting part of software development, at least not for me, so I was happy to let Claude work on it. I was pretty much on autopilot.

But after a couple of days, I started wondering what was going on. Why was this taking so long? Was I getting throttled? What exactly was Claude doing?

Turns out, Claude was building a full-blown, professional-grade testing harness. Something that could probably compete with products already on the market.

I didn't need a testing product. I needed to test my product!

And the funny thing is, Claude hadn't really done anything wrong. I had asked it to improve the testing process, and it was doing exactly that. I hadn't told it to consider existing tools, or that building our own testing infrastructure wasn't an acceptable use of time.

The goal was underspecified, and the agent pursued what it considered a reasonable solution.

I'd like to think I could simply write a better prompt next time. But the reality is, details will get missed. We're still human, after all.

And as projects grow, there are more decisions, constraints, and assumptions to remember than any one prompt can reasonably capture.

Better prompts definitely help. So does reviewing what agents are doing along the way. But once you've made a decision, you shouldn't have to remember to repeat it every time a new agent starts working.

That experience got me thinking about a larger problem: **How do you keep agents working within the decisions and constraints you've already established, without having to explain everything all over again?**

## From developer to conductor

I don't know if there's an official name for working this way. I just call it multi-agent development.

And I think it's an incredibly useful way to build software. With the right approach, a small team, or even one person, can accomplish things that would have required a much larger team not long ago.

But there's a catch. You have to manage it carefully.

Your role changes. You're not necessarily the person writing the code anymore. You're more like a product owner and conductor, with each agent playing a different part in the orchestra.

And just like a real orchestra, the players need to know more than their individual parts. They need to understand the music, the timing, the conductor's direction, and how their work fits into the whole.

Now imagine the musicians keep coming and going.

That's essentially what happens with AI agents. Sessions reach their limits. New sessions begin. Agents get brought in for specialized work, sometimes long after the project started. One agent may have participated in weeks of design discussions, while another is joining for the first time.

Meanwhile, your project keeps evolving.

Decisions get made. Assumptions change. Features get added, modified, or removed. Earlier approaches are abandoned. Some ideas are still being considered, while others have become firm decisions.

Keeping all of that straight becomes a real job.

And just because something was decided in one conversation doesn't mean another agent knows about it. Even the same agent, in a new session, may not have the context that led to the decision.

And even when an agent can retrieve an earlier discussion, that doesn't necessarily tell it which decisions are still valid.

That's an important distinction. There's a difference between remembering what was discussed and knowing what actually governs the project.

You can spend a surprising amount of time repeating yourself, correcting misunderstandings, and making sure agents aren't working from outdated assumptions.

And the faster the agents work, the faster these coordination problems can accumulate.

This is where I started to realize that the challenge wasn't just writing better prompts or giving agents more information. It was finding a reliable way to preserve the decisions we'd already made, distinguish them from ideas still being explored, and make those decisions available to everyone working on the project.

## Where Charter comes in

This is the problem that led me to build Charter.

Charter is a small, local, version-controlled home for the decisions that govern a software project.

The idea is fairly simple: as your project evolves, some decisions become authoritative. They define what you're building, how it should work, and the architectural or product constraints that agents should be working within.

Those decisions shouldn't live only in a conversation that might eventually disappear from an agent's working context.

And simply accumulating more documentation isn't necessarily the answer either. A collection of notes, proposals, outdated specifications, and approved decisions can leave an agent with plenty of information, but little clarity about which information it should follow.

With Charter, you maintain a shared body of governing context that agents can retrieve, regardless of which agent they are or when they join the project.

Agents can also help maintain that context. They can draft new material, propose changes to existing decisions, and help organize the information. But proposed changes don't become authoritative just because an agent suggested them.

You review and approve what governs your project.

That's an important distinction. Charter isn't a sandbox, and it doesn't prevent an agent with file access from making changes directly. What it does is make the approved decisions explicit, reviewable, and available through a consistent route.

It gives agents a common reference point, while keeping the human in control of what is authoritative.

Charter isn't intended to replace good prompting, agent supervision, or the other tools we already use to build software. It's meant to complement them by addressing one particular challenge: keeping a project's governing decisions clear and accessible as the project, and the people and agents working on it, continue to change.

The goal isn't to eliminate every mistake or prevent every instance of drift. It's to reduce the coordination overhead and make it easier for agents to work from the same understanding of the project.

## What's next

Over the next seven posts, I'll be introducing Charter, exploring the ideas behind it, and sharing some of the workflows I've developed while building software with multiple AI agents.

We'll start with the coordination problem itself, then work our way toward some practical examples of using Charter.

Here's what I have planned:

1. **The missing layer in AI-assisted development: governing context.** Why prompts, session memory, and more documentation aren't necessarily enough, and what it means to establish a shared source of project decisions.
2. **What should govern an agent—and what should not?** The difference between approved decisions, working notes, proposals, and other project information. Not everything an agent can read should be treated as authoritative.
3. **What is Charter?** A closer look at the tool, how it works, and where it fits alongside instruction files and other context-management approaches.
4. **Agents can propose; people decide.** How agents can help create and maintain governing context without automatically gaining the authority to change it.
5. **One context, many agents.** How different agents and sessions can retrieve the same governing context, including the role MCP plays in making that possible—and why making context available isn't the same as guaranteeing an agent will follow it.
6. **Charter, Git, and the shape of a durable project context.** Where governing context lives, how version control fits into the picture, and why Git history and human approval serve different purposes.
7. **Your first governing context: start small, keep it useful.** A practical walkthrough of getting started with Charter, without turning context management into another project of its own.

The code is available for free. Use it however you wish.

I'd love to hear what others are doing in this space. If you're building software with multiple agents, how are you managing project context? What tools or workflows have you found useful?

And if you give Charter a try, I'd love to hear what you think.
