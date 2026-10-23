---
layout: article
title: "Part 2 — The Problem"
description: "The Missing Layer: Governing Context"
permalink: /the-problem/
---

# Part 2 — The Problem

## The Missing Layer: Governing Context

In the introduction, I described how working with multiple AI agents can create a growing coordination problem. But to be fair, this isn't strictly a multi-agent issue. You can encounter it using a single agent, too.

Every agent has a limited amount of working context. As conversations grow, older information may be summarized, omitted, or become unavailable in subsequent sessions.

With multiple agents, you also have different conversation histories and different understandings of the project.

Here's a simple example.

### When a bug isn't a bug

Let's say you're building an application where customers can place and modify orders.

Early in development, you make an important product decision: customers can change their orders freely until production begins. After that, changes must go through a formal change-request process.

Makes sense. You don't want customers changing an order while someone is already building it.

You work through the requirements with your product design agent, pass them to your development agent, and the feature gets built. Everything works.

Weeks later, you bring in another agent to test the application. It notices that customers can't edit certain orders and flags this as a bug.

So, you ask your development agent to fix it.

By now, that agent may no longer have the original design discussion in its working context. It investigates, finds the restriction, and removes it.

Great, bug fixed!

Except it wasn't a bug.

That restriction was an intentional business rule; one you'd discussed and approved weeks earlier. And now you've got two agents, both doing what they thought was helpful, that together have undone an important product decision.

Of course, a careful review might have caught this. But the larger problem is that neither agent had a reliable reference for the decision that governed the feature.

### A common source isn't necessarily a source of truth

The first solution seems fairly obvious: store your product specifications and important decisions somewhere central, where every agent can access them.

You can direct agents to this information through their instructions or files like CLAUDE.md and AGENTS.md.

That's a big improvement. Now you're no longer relying entirely on conversation history.

But there's another challenge.

Let's say that, a few weeks later, you start exploring whether customers should be allowed to request order changes during production.

Your product design agent creates a proposal. Your development agent writes some technical notes about how it might work. Meanwhile, your original specification still describes the approved business rule.

Now you have three documents: the original specification, a proposal, and some technical notes.

All three contain useful information.

But only one represents the current approved behavior.

What happens when another agent retrieves all three? Does it know which one to follow?

Maybe the proposal is newer. Maybe the technical notes describe an approach that was never approved. Maybe you considered the change and decided against it.

Simply making information available doesn't tell an agent which decisions are authoritative.

***And that's the distinction that matters: there's a difference between information an agent can use and decisions an agent is expected to work within.***
{: .pull-quote}

### Governing context

This is what I mean by *governing context*.

Governing context is the collection of approved decisions, requirements, and constraints that define how a project is supposed to work.

It might include product specifications, architectural decisions, business rules, or other requirements that agents are expected to respect.

The important point is that not everything discussed or documented becomes governing context.

An idea isn't necessarily a decision. A proposal isn't automatically approved. And an older specification may no longer reflect how the product is supposed to work.

Someone has to decide what is authoritative.

In my workflow, that someone is me, acting as the product owner.

Agents are extremely useful for researching, designing, and proposing changes. But I want to decide which proposals become part of the project's governing context.

And when those decisions change, I want that context updated so future agents have access to the current understanding.

That doesn't guarantee agents will always follow it perfectly. But it gives them a consistent reference, independent of any one conversation or session.

For me, that was the missing piece.

The challenge wasn't simply giving agents more context.

***It was making sure they could distinguish what had been discussed from what had actually been decided.***
{: .pull-quote}

And that raises the next question: what belongs in governing context, and who gets to change it?

That's where the principles behind Charter come in.
