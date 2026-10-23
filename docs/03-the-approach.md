---
layout: article
title: "Part 3 — The Approach"
description: "Agents Can Propose. People Decide."
permalink: /the-approach/
---

# Part 3 — The Approach

## Agents Can Propose. People Decide.

In the previous section, we introduced the idea of governing context: the decisions, requirements, and constraints that define how a project is supposed to work.

But there's an interesting question. Who gets to decide what belongs in that context?

When you're working with AI agents, it's tempting to let them maintain the documentation themselves. They're good at writing specifications, identifying inconsistencies, and organizing information. Why not let them update the project's governing context as they work?

Well, because documenting a decision and making a decision are two different things.
{: .pull-quote}

### Not everything should govern

Think about the information that accumulates during software development.

You have product specifications, architectural decisions, technical notes, proposed features, rejected ideas, and experiments that may or may not go anywhere.

All of that can be useful. But not all of it should influence how an agent implements your product.

For example, suppose an agent recommends replacing your database with something it considers more scalable. It might be a good recommendation, and you might want to explore it.

But until you've evaluated the tradeoffs and decided to proceed, it's still a proposal.

If that recommendation quietly makes its way into your governing context, another agent might treat it as an approved architectural decision.

Now you've got agents implementing a change you never agreed to.

The distinction seems obvious when you think about it. But when agents are producing documents, plans, and code at the pace they do, it's easy for the lines to blur.

### The human approval boundary

My approach is fairly simple: agents can contribute to governing context, but they don't get to decide what becomes authoritative.
{: .pull-quote}

An agent can research a problem, recommend a solution, draft a specification, or propose changing an existing decision.

I want all of that help.

But before that proposed change becomes part of the project's governing context, I review it and decide whether to accept it.

Sometimes I accept a proposal as written. Sometimes I ask for revisions. And sometimes I reject it because the approach doesn't fit the product or would introduce complexity I don't want.

This doesn't mean I need to write every specification myself. Quite the opposite. One of the biggest benefits of working with AI agents is how much of that work they can help produce.

I'm simply separating the work of *developing a proposal* from the authority to *approve a decision*.

### Keeping context current

There's another side to this.

Governing context can't become a collection of decisions that nobody ever updates. Projects evolve. Requirements change. Earlier decisions get replaced.

The objective isn't to freeze the project. It's to make those changes deliberate.

When a decision changes, the governing context should change with it. Otherwise, your agents may continue working from requirements that are no longer valid.

This is the principle I wanted to preserve when I started building Charter: agents should be able to help evolve the project's context, while the human remains responsible for deciding what governs.

Of course, Charter isn't a sandbox. An agent with direct file access can still change a document outside Charter's review process.

Charter makes changes through its own workflow deliberate and reviewable. Its integrity checks can detect inconsistencies, but they don't establish who wrote or approved every change.

So, the approach is straightforward: keep approved decisions separate from working material, let agents contribute proposals, and make changes to governing context intentional.

The next question is how to make that practical without creating another administrative burden.

That's where Charter comes in.
