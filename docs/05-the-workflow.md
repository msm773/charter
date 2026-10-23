---
layout: article
title: "Part 5 — The Workflow"
description: "Putting Charter to Work"
permalink: /the-workflow/
---

# Part 5 — The Workflow

## Putting Charter to Work

One thing I've learned from building software with AI agents is that it's surprisingly easy to spend too much time building tools to help you build your tools.

My testing-harness experience was a pretty good reminder of that.

So when I started working on Charter, I wanted it to be useful without requiring a lot of ongoing administration.

The objective isn't to document everything. It's to preserve the decisions that matter and make them available when agents need them.
{: .pull-quote}

### Start with what matters

Let's say you're beginning a new software project.

You don't need to write a hundred-page specification before you start. In fact, I'd recommend against it.

Start with a small amount of governing context. What are you building? What are the important product requirements? Are there architectural decisions or constraints you already know you want to preserve?

You can use an AI agent to help draft this material. That's often much easier than writing it all yourself.

Then review it, make any necessary changes, and establish the approved material as your governing context.

Now you have a starting point that exists outside any one conversation.

### Connect your agents

Next, configure the agents you're using to access Charter.

For agents that support MCP, Charter exposes tools for retrieving governing context and submitting proposals.

You can also use project instruction files to direct agents to the governing material.

For example, when I start a new development session, I want the agent to retrieve the current project context before it starts making changes.

That gives us a common starting point.

It doesn't mean the agent will never misunderstand a requirement, but it reduces the amount of context I need to reconstruct every time a session changes.

### Let the project evolve

Now imagine you're several weeks into development.

You've built a number of features, made some adjustments, and discovered that an earlier architectural decision needs to change.

You work through the issue with an agent. Maybe it researches alternatives, identifies tradeoffs, and recommends an approach.

Once you're satisfied with the direction, the agent can help prepare a proposed change to the governing context.

You accept the proposal as a candidate, review and refine it, then include it in a change set. After previewing the result, you confirm the change.

Only then are the governing documents updated to reflect the new decision.

The next time an agent retrieves that context, the updated decision is available.

You haven't had to manually explain the change to every agent or depend on each one remembering the discussion that led to it.

And there's another benefit I've found particularly useful: once your governing context is established, your prompts can become a lot simpler.

Rather than explaining all the requirements and decisions every time I start a new feature, I often ask the agent to review the relevant governing context and develop an implementation plan.

I can then review the plan, make adjustments where necessary, and approve it before the agent starts building. Quite often, the initial plan is already close to what I had in mind.

I'm still making the important decisions, but I'm spending less time repeating things we've already decided and more time reviewing the work I actually want done.

Of course, you still need to ensure your agents retrieve and use the context when appropriate. Charter doesn't supervise their work or enforce compliance.

But it provides a common reference that remains available as the project continues.

### Keep it useful

There's a temptation, particularly when working with AI, to generate more documentation simply because it's easy to do.

I think that's worth resisting.

More information isn't automatically better context. Too much material can make it harder for agents to identify what's important, and maintaining unnecessary documents creates work of its own.

I'd start small and let the context grow as the project requires it.

If a decision matters enough that you'd be frustrated having to explain it again—or having an agent accidentally reverse it—it's probably a good candidate for governing context.

If it's just an idea you're considering or a temporary note from an investigation, it probably doesn't need to govern anything yet.

The point is to make context management serve the development process, not become another project you're managing.

### A tool, not a requirement

Charter is one approach to this problem, and certainly not the only one.

You can manage governing context with ordinary files, carefully maintained project instructions, and your own review process.

That's essentially where I started.

Charter grew out of wanting a more consistent way to manage that process as my projects became larger and more complex.

And while I built it primarily for my own development workflow, I decided to make it available for others to use.

It's free, and the source code is available on GitHub.

If you're building software with AI agents, I'd encourage you to think about how you're preserving the decisions that govern your project, regardless of whether you use Charter.

For me, one of the biggest benefits is that I'm no longer constantly reconstructing the past so an agent can do the next piece of work. I'm using established decisions to move forward.
{: .pull-quote}

Because the faster we can build software, the more important it becomes to keep track of what we're actually building.

That's the problem Charter was created to help solve.

**Charter — Agent Context Manager**

*One trusted context for every AI agent on your project.*

[Explore Charter on GitHub](https://github.com/msm773/charter)
