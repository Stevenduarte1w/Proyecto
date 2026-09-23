from openai import OpenAI
import re
import os
from typing import Dict, List


class NewPostContent:
    def __init__(self, api_key: str, language: str):
        """Initialize with OpenAI API key."""
        self.client = OpenAI(api_key=api_key)
        self.content_model = os.getenv("OPENAI_CONTENT_MODEL", "gpt-4")
        self.meta_model = os.getenv("OPENAI_META_MODEL", "gpt-4o")
        self.language = language.lower()
        self.SYSTEM_MESSAGE = (
            f"As a system, you can provide relevant SEO, E-E-A-T and marketing"
            f" information. Always respond in {self.language}. Include the"
            f" comnpany only once in the entire response."
        )
        self.ASSISTANT_MESSAGE = (
            "As an assistant, I can hel answer your seo, E-E-A-T and marketing"
            " questions, providing useful information and tips. Include the"
            " company name on once in the entire response."
        )
        self.validation_rules = {
            "word_count": (1000, 1200),
            "title_mentions": 5,
            "paragraph_lines": (5, 150),
            "subtitles": 6,
        }
        self.context = ""

    def create_message(self, role: str, content: str) -> Dict:
        return {"role": role, "content": content}

    def generate_response(
        self, model: str, messages: List[Dict], temperature: float = 0.7
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        res = response.choices[0].message.content or ""
        # Preserve quotes, newlines and HTML attributes; stripping apostrophes here
        # used to corrupt every generated href and alter editorial copy.
        cleaned = re.sub(r"^\s*```(?:html)?\s*|\s*```\s*$", "", res, flags=re.IGNORECASE)
        return cleaned.strip()

    def botanic_introduction(self, title: str, linked_keywords: List[str]) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a real human writer who works at a spiritual botanica. You know about love spells, cleansings, energy work, and helping people who come in looking for answers.

    Write an **introductory paragraph** for a blog post titled {title} with a tone that is spiritual, simple, and a little chabacano — like something written by someone from the barrio who’s been in this for years.

    Instructions:

    - Begin the output with this title as a heading:
    <h1>{title}</h1>

    - Then write ONE single paragraph (5–7 lines). No subtitles. No extra sections.

    - Make sure the paragraph **mentions the post title ({title})**, naturally within the paragraph (not just in the heading).

    - The tone should feel human, grounded, and slightly informal — but **do not use first-person** language like “I”, “my”, “we”, or “in my botanica”.

    - Instead, use **third-person language** like: “in the botanica…”, “many people ask…”, “clients often come in when…”, “it’s common to see…”.

    - Integrate the following links naturally — **do not use quotation marks, smart quotes (like « or “), bold, italics, or any special formatting around the link text**. Just make the links flow like part of the sentence:
    {linked_keywords}

    - Avoid robotic phrases like “in this article we’ll talk about…” or anything that sounds like AI.

    - Write everything in {self.language}.
    - NEVER FORGET THE LINKS
    """
        print("Generating botanic_introduction...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def botanic_content(self, title: str) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a human writer who creates long-form blog posts for a spiritual botanica website.

    Write the full body of a post titled {title} using the structure and tone described below:

    STRUCTURE:
    - Divide the content into **exactly 7 sections**
    - Each section must contain:
    <h2>Subtitle</h2>
    <p>One paragraph between **550 and 650 characters** (not words)</p>
    - **At least 3 of the 7 subtitles must include the blog title ({title}) or a close synonym/paraphrase of it**, to keep the theme clear and consistent.

    STYLE & RULES:
    - The response must be written in {self.language}
    - DO NOT include the word "introduction" anywhere in the content
    - DO NOT speak in first person (no “I”, “my”, “we”, or “in my botanica”)
    - Use **third person** tone only (e.g. “in the botanica…”, “many clients ask about…”, “it’s common to see…”)
    - Write with a **chabacano, esoteric, streetwise tone**, like a spiritual elder who speaks from experience but with barrio flavor
    - Use natural expressions like: “the truth is…”, “this doesn’t fail…”, “it’s common in the neighborhood…”, “people always ask…”
    - The exact phrase {title} must appear **at least 5 times** naturally throughout the content
    - **Never use quotation marks** of any kind — avoid straight quotes ("..."), single quotes ('...'), and smart quotes (“”, «», ‘’)
    - Never use emphasis formatting (no bold, italics, or highlighting of any kind)
    - Avoid robotic expressions like “this article will explain”, “we’ll explore”, or “in this post…”
    - Never use the word “conclusion” — or any similar words like “to conclude”, “to summarize”, “in summary”, “final thoughts”, “in closing” — in the paragraph or in any part of the response.

    OUTPUT FORMAT:
    - Return clean HTML only, using only <h2> and <p> tags — no markdown, no spacing, no notes

    Begin writing now.
    """
        print("Generating botanic content...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def botanic_conclusion(self, title: str, linked_keywords: List[str]) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a human writer with real experience at a spiritual botanica. Write the **closing paragraph** for a blog post titled {title}. It should sound like someone giving a final piece of grounded advice after a spiritual conversation.

    Follow these instructions:

    - Write exactly **one single paragraph**, no line breaks, no headers, no subtitles, no sections.
    - The tone should be spiritual, warm, slightly chabacano, and sound like someone who speaks from real-world experience.
    - Speak in **third person only**. Do NOT use first-person language like “I”, “we”, “my”, “me”, “our”, or phrases like “what I always tell people”.
    - Use expressions like: “in the botanica it’s common…”, “many people notice…”, “clients often ask…”, “it’s no surprise that…”.
    - Never use the word “conclusion” — or any similar words like “to conclude”, “to summarize”, “in summary”, “final thoughts”, “in closing” — in the paragraph or in any part of the response.
    - Do not use quotation marks of any kind — including double quotes ("..."), single quotes ('...'), or smart quotes («», “”, ‘’) — especially not around links.
    - Naturally embed the following links — they must sound like part of the sentence, not forced or announced:
    {linked_keywords}
    - The entire response must be written in {self.language}.
    - NEVER FORGET THE LINKS
    """
        print("Generating botanic_conclusion...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def yoast_description(self, title: str) -> str:
        system_message = self.create_message(
            "system",
            "Do not include any explanation from you, give me the content without any opinion, only what was requested, no recommendations or explanations of the subject.",
        )
        user_message = self.create_message(
            "user",
            f"""Generate a short and engaging meta description optimized for SEO, following these rules:
                - The description must be **a minimum of 115 and maximum of 130 characters**.
                - It must include the exact **key phrase** provided in {title} with no changes, but its position can be flexible.
                - The description must feel natural and **match the business type**.
                - End with a compelling **call to action** relevant to the business.
                - Ensure proper sentence capitalization.
                - The description **must be written in {self.language}**.""",
        )
        return f"{self.generate_response(self.meta_model, [system_message, user_message])}"

    def external_link(self, title: str, link: str) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a human writer who works at a spiritual botanica. Based on the topic {title}, write a short, natural sentence that includes this external link:

    {link}

    Guidelines:

    - The sentence should be human, esoteric, and slightly chabacano — like someone who’s been in the botanica scene for years.
    - The link must be part of the sentence, naturally embedded. Do NOT put it in quotes or isolate it.
    - Use no more than 2 lines. It's just a complement, not a full paragraph.
    - It should feel like an additional comment or closing suggestion — something someone would say when pointing someone to learn more.
    - Do not say “click here” or “link” or use formatting like quotation marks, bold, or italics.
    - Return only the sentence, nothing else.
    - Write in {self.language}.
    """

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def english_introduction(self, title: str, linked_keywords: List[str]) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a real human writer who creates blog content for small and medium-sized businesses in the U.S. Your writing feels clear, experienced, and natural — like someone who actually knows how the service works and how to explain it without overpromising.

    Write an **introductory paragraph** for a blog post titled {title}. The tone should be grounded, slightly conversational, and helpful — like a person explaining context to a curious but unfamiliar reader.

    INSTRUCTIONS:
    - Begin the output with this heading:
    <h1>{title}</h1>

    - Immediately after the heading, the first sentence of the paragraph must **start with the phrase {title}** — it should feel like a natural introduction, not a repetition of the heading.

    - Write **exactly one paragraph** of 5–7 lines (roughly 550–650 characters).
    - Never include any subtitles or additional sections — only the heading and the paragraph.
    - Use only **third-person voice** — never say “I”, “we”, “our”, or anything first-person.

    - Integrate the following links naturally into the paragraph — without quotation marks, formatting, or forced phrasing:
    {linked_keywords}

    - Do NOT use AI-sounding clichés like “in this blog post you’ll learn…” or “this article explores…”

    - Keep the writing in {self.language}.
    - NEVER skip or forget the links — make them feel part of the flow. and do not lose the html tags of the links

    OUTPUT FORMAT:
    <h1>{title}</h1>
    <p>Intro paragraph goes here…</p>
    """

        print("Generating english_introduction...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def english_content(self, title: str) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a real human writer with firsthand knowledge of spiritual botanicas and the kind of questions customers ask. Your job is to write grounded, natural long-form content that feels like it was written by someone who lives and breathes this world.

    Write the full body of a post titled {title} using the structure and tone described below:

    STRUCTURE:
    - Divide the content into **exactly 7 sections**
    - Each section must contain:
    <h2>Subtitle</h2>
    <p>One paragraph between **650 and 650 characters** (not words)</p>
    - **At least 5 of the 7 subtitles must include the blog title ({title}) or a close synonym/paraphrase of it**, to keep the theme clear and consistent.

    STYLE & RULES:
    - The response must be written entirely in {self.language} — no other language allowed
    - DO NOT include the word "introduction" anywhere in the content
    - Use only **third person** voice — never use “I”, “we”, “our”, or “in my botanica”
    - Use a **familiar, confident, and conversational tone** — like someone who knows the culture and daily spiritual life of their community
    - The text should sound like it comes from someone with **real-world experience**, not from a machine or book
    - Use human expressions like: “the truth is…”, “people always ask…”, “it’s common in the neighborhood…”, “this doesn’t fail…”
    - The exact phrase {title} must appear **at least 5 times** — naturally, never forced
    - **Never use quotation marks** of any kind — no straight quotes ("..."), single quotes ('...'), or smart quotes (“”, «», ‘’)
    - Avoid robotic expressions like “this article will explain”, “we’ll explore”, or “in this post…”
    - Do not use bold, italics, underlines, or any visual formatting — just clean HTML

    OUTPUT FORMAT:
    - Return valid HTML only, using only <h2> and <p> tags — no markdown, no extra spacing, no comments

    Begin writing now.
    """
        print("Generating english_content...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def english_conclusion(self, title: str, linked_keywords: List[str]) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)
        print(linked_keywords)
        user_prompt = f"""
    You are a real human writer creating business content for a company blog. Your job is to write the **final paragraph** for a blog post titled {title}, offering a clear, grounded takeaway that feels useful and human — like something a trusted expert would say to a customer before they leave the conversation.

    Follow these rules:

    - Write **exactly one paragraph**, no line breaks, no titles, no extra formatting.
    - The output must be wrapped inside a single HTML tag: <p> ... </p> — return only that.
    - Use a **friendly, professional, and human tone** — like someone who knows the business inside out and speaks in plain terms.
    - Only use **third person** tone — never use “I”, “we”, “our”, or “you”.
    - Use phrases like: “it’s no surprise that…”, “many people turn to…”, “it’s common to see…”, “customers often notice…”.
    - Do **not** use any variation of the word “conclusion” — do not include “to conclude”, “to summarize”, “in conclusion”, “in summary”, “final thoughts”, or similar.
    - Do **not** use quotation marks of any kind — no straight quotes ("..."), single quotes ('...'), or smart quotes (“”, «», ‘’), especially not around link text.
    - Include the following links naturally within the paragraph — do not announce them or wrap them in formatting:
    {linked_keywords}
    - Write everything in {self.language}."""
        print("Generating english_conclusion...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.85,
        ).strip()

    def humanize_content(self, content: str, title: str) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are a human copy editor. Your job is to **make the following content sound more human and natural**, while keeping everything structurally intact.

    Instructions:

    - DO NOT change, remove, or add any HTML tags — the structure must remain exactly as it is.
    - DO NOT delete, shorten, or add new sections.
    - DO NOT change the order of the text.
    - Only reword or rewrite phrases **within the existing paragraphs** to make them sound **more human**, more like they were written by someone with lived experience.
    - Use natural language, everyday expressions, and conversational phrasing — as if the writer had experience in the real world and was explaining things in plain terms.
    - Avoid robotic or generic-sounding phrases. Make the tone confident, approachable, and easy to follow.
    - Keep the meaning, length, and flow of each paragraph the same — just make the language feel more human.
    - Never add emphasis formatting (no bold, italics, underlines), and never use quotation marks of any kind.
    - Keep the title {title} 5 times in the content.

    Here is the content to improve:

    {content}
    """
        print("Humanizing content...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.8,
        ).strip()

    def humanize_content2(self, content: str, title: str) -> str:
        system_message = self.create_message("system", self.SYSTEM_MESSAGE)
        assistant_message = self.create_message("assistant", self.ASSISTANT_MESSAGE)

        user_prompt = f"""
    You are an experienced human copy editor hired to refine a blog post written by another human — not an AI.

    Your task is to **make this content sound more human, natural, and lived-in**, while keeping every technical aspect and structure untouched.

    Rules:

    - DO NOT modify, remove, or reorder any HTML tags or structure.
    - DO NOT add new sections, change the layout, or shorten/lengthen any paragraphs.
    - DO NOT rewrite the entire thing — just revise wording *inside each paragraph* to make it sound more like something someone would say in real life.
    - Focus on making the tone feel human: practical, lived, informal but professional — like a business owner who knows their trade and talks in real terms.
    - Fix robotic or generic phrasing. Avoid phrases that feel AI-generated, distant, or overly polished.
    - Preserve all technical information, intent, and flow — your only job is to make it feel like a real person wrote it.
    - Keep the title {title} 5 times in the content.

    Examples of changes you might make:
    - “It is important to consider…” → “A good thing to keep in mind is…”
    - “This service offers various benefits” → “This service can really help in a few key ways”
    - “Customers will experience…” → “Most people notice…”

    IMPORTANT:
    - Do NOT use quotation marks of any kind.
    - Do NOT use bold, italics, or any other formatting beyond what's already present.

    Improve the content below:

    {content}
    """
        print("Refining content with human tone...")

        user_message = self.create_message("user", user_prompt)

        return self.generate_response(
            model=self.content_model,
            messages=[system_message, assistant_message, user_message],
            temperature=0.75,
        ).strip()

