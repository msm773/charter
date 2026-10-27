---
layout: article
title: "Before the Agent Writes Code: A Workflow for Building Products with AI Agents"
description: "How a proposal-and-review workflow helped establish a shared understanding with AI agents—and eventually led to Charter."
permalink: /before-the-agent-writes-code/
---

# Before the Agent Writes Code: A Workflow for Building Products with AI Agents

## How a proposal-and-review workflow helped establish a shared understanding with AI agents—and eventually led to Charter.

![A developer conducts an orchestra of AI agents, including an enthusiastic washboard player.]({{ '/assets/images/articles/agent-orchestra.webp' | relative_url }})

Developing a complete software product with AI agents turns out to be a lot of work, actually.

Instead of writing code, you become a conductor, a critic, and occasionally a referee, but most importantly, you must be the communicator.

After decades of delivering software, one of the biggest lessons from building with agents was: good specifications aren't necessarily enough.

What is needed, it turns out, is simple: Communication.

Communication between human and agent. Communication between agent and agent.

Good specifications are essential, of course. Without them, you don't know where you're going, and neither do your agents. You might get somewhere, but you won't necessarily know when you've arrived.

But establishing a shared understanding among all parties involved turns out to be a real challenge with agents. It’s one thing to provide the specs, another to validate agents understand them.


### My First Build

I was building Studio, a SaaS product that helps custom makers manage projects collaboratively with their customers, from early design discussions through delivery.

I needed a development team. Fortunately, I had one.

ChatGPT became my product-definition partner, helping turn ideas into requirements and specifications. Claude served as architect and developer, with direct access to the codebase. Claude and Codex also helped with testing, although Codex took on a particularly useful role as an adversarial tester, trying to break what Claude had built.

And I was the product owner, making decisions and trying to keep everyone headed in the same direction.

Not a bad arrangement.

At first, the development process was straightforward. I'd work with ChatGPT to define a feature, review the resulting specification, and pass it to Claude for implementation.

Sometimes that worked beautifully. But sometimes it also failed spectacularly.

Other times, Claude built a perfectly functional feature that just wasn't quite as intended.

Usually, after a lot of back and forth with ChatGPT and Claude, we’d get it figured out.

But this took time, and sometimes a lot of it. Not quite the productivity revolution I'd imagined.


### The Copy-and-Paste Department

As Studio grew, so did the specifications, architectural decisions, UI rules, and dependencies. Communicating with the agents became increasingly difficult.

My first solution was simple. I began collecting specifications and engineering decisions, then providing the relevant documents whenever I assigned work.

That helped. The agents had more information, and the results improved.

Unfortunately, I'd also promoted myself to the copy-and-paste department.

Share the specification with ChatGPT and work out a prompt. Copy the prompt. Go to Claude, paste the prompt and attach the specifications. Watch Claude work. Review the results. Determine if we succeeded or needed more work. If more work, repeat, copy, paste.


### When the Magic Started Wearing Off

Eventually, enough of Studio existed that I could begin testing the application as a whole.

At first, this was genuinely exciting. Working features everywhere, and I hadn't written a line of code.

But then I looked more closely.

Labels that didn't quite make sense. Buttons in odd places. Inconsistent layouts. Missing features, unexpected behavior, and occasionally features I hadn't requested.

In fairness, some of those unexpected features were actually pretty good. Why hadn't I thought of them?

Still, the more I tested, the more the magic began to fade.

The agents had built a substantial working application. That was remarkable.

It just wasn't quite the application we'd intended.

So, I expanded the team and began testing, using multiple agents to run different types of tests overnight.

I'd wake up to reports of defects organized by severity.

Now, this was impressive, an entire QA team working while I slept.

Of course, it also meant an impressive collection of problems to fix.

Hours became days. Days became weeks.

Some of this was ordinary software development. Bugs happen, requirements change, and integration is never quite as simple as we'd like.

But two problems were becoming clear.

1. Maintaining the project's specifications and decisions was getting difficult. Some documents were outdated, others conflicted, and agents didn't always find the information they needed.
2. I couldn't always tell whether Claude understood what we wanted until after it had already built something.

More documentation helped with the first problem, but it didn't necessarily solve the second.

I needed to change how my “team” worked.


### The 15 GB Test Suite

One evening, I asked Claude to create several types of tests, run them overnight, and report the results in a format I could review the next morning.

Simple enough.

The next morning, Claude was still working.

By the afternoon, it was still working.

I wondered whether my computer had gone to sleep or whether I'd been throttled. Claude assured me it was making progress.

Then, almost by accident, I opened the project directory in Windows Explorer.

My relatively small Angular project had grown to 15 GB.

What on earth was Claude building?

As it turned out, an entire testing infrastructure: a harness, an execution engine, real-time monitoring, reporting—the works.

A rather ambitious project in its own right.

And when I reviewed the original request, I couldn't entirely blame Claude.

What seemed obvious to me hadn't necessarily been obvious to the agent. It had selected an approach that made sense from its interpretation of the instructions.

The problem wasn't necessarily Claude's ability to build. It was that I hadn't established what Claude intended to build before letting it begin.

That experience helped me form a key pillar for a new workflow.


### Before the Agent Writes Code

Instead of immediately authorizing implementation, I began asking Claude to review the request against the existing codebase, specifications, and architectural decisions, then return a proposal.

What did Claude understand we wanted? How would it approach development given the existing code base? What necessary changes, if any, did Claude identify? Were there conflicts with other specifications, risks to other parts of the application, or better alternatives to the proposed request I provided?

I'd then review Claude’s proposal with ChatGPT, challenge assumptions, revise the request, and repeat as necessary.

Sometimes Claude identified a misunderstanding. Sometimes it found weaknesses in our specification. Occasionally, it suggested an approach we hadn't considered. Quite often, ChatGPT also found issues in Claude’s plan, or understanding, as well.

Only when I was satisfied with the proposal would I authorize implementation.

And that made a difference.

I wasn’t simply improving the instructions. I was creating an opportunity to examine the agent's interpretation of those instructions before it turned them into code.

The results improved, and I spent less time discovering fundamental misunderstandings after implementation. However, side note, copying and pasting increased.


### The Workflow We Settled Into

Eventually, our development cycle looked something like this:

1. **Explore and specify.** Work with ChatGPT to define the feature, consider alternatives, and prepare an implementation request.
2. **Review and propose.** Have Claude examine the request against the code base and governing documents, then explain its intended approach.
3. **Discuss and refine.** Review the proposal, resolve questions, and iterate until satisfied.
4. **Approve and implement.** Explicitly authorize Claude to build, preserving the accepted specifications and decisions.
5. **Verify and correct.** Use Claude and Codex for testing, review defects, and repeat until the results are satisfactory.
6. **Test it myself.** Use the application and verify that it actually behaves as intended.

Separating reviewing a proposed approach from authorizing implementation became one of the most valuable changes I made.

Unfortunately, I was still spending an extraordinary amount of time copying documents, reconciling decisions, and preparing the next session.

I had improved the shared understanding among agents, but maintaining that understanding was another matter.


### The Problem That Led to Charter

By this point, the workflow was working. But managing the project knowledge behind it was becoming a job of its own.

I needed a way to preserve accepted requirements and architectural decisions, distinguish them from proposals, and make that governing context available across agents and sessions.

That's how Charter came about.

Charter is a free, open-source tool I built to help maintain trusted governing project documents. Agents can propose changes, but a human decides what becomes authoritative.

It's worth distinguishing this from managing an individual agent's working context. Charter is concerned with what the project has accepted as governing, not everything an agent happens to have in its context window.

The tool doesn't orchestrate agents, write code, or verify implementations. It simply addresses one of the problems we encountered while doing those things.

You can explore [Charter on GitHub](https://github.com/msm773/Charter).


### What I Took Away from All This

Looking back, what surprises me most isn't how much code the agents wrote. It's how much work went into making sure we understood what we were trying to accomplish.

A good specification helped. Relevant context helped. But asking the agent to explain its proposed approach before implementation made a particularly important difference.

Giving an agent the right information, establishing that it has interpreted that information appropriately, and verifying what it actually builds are three different problems.

The workflow helped to manage all three. Charter made one part easier.

Would I use exactly the same process for every task or project? Probably not. Some changes hardly warrant a formal proposal; others benefit enormously from a little discussion before anyone starts writing code.

And I suspect our tools and ways of working will continue to evolve.

I set out to build a software product with AI agents. Along the way, I developed an engineering workflow, built another tool to support it, and learned quite a bit about communicating with machines.

Not quite what I'd expected.

Then again, that's what makes this stuff interesting.

For those of you building larger projects with AI agents, how are you establishing shared understanding before implementation? Have you developed workflows of your own?
