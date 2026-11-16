// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';

/**
 * Tailwind overrides so a parsed document reads like a document, not like
 * source. Shared by the batch preview and the stored-instance detail view so
 * the same answer cannot look different depending on when it was opened.
 */
const MARKDOWN_COMPONENTS = {
	h1: (props: object) => <h1 className="mt-4 mb-2 text-lg font-semibold" {...props} />,
	h2: (props: object) => <h2 className="mt-4 mb-2 text-base font-semibold" {...props} />,
	h3: (props: object) => <h3 className="mt-3 mb-1.5 text-sm font-semibold" {...props} />,
	p: (props: object) => <p className="my-2 leading-relaxed" {...props} />,
	ul: (props: object) => <ul className="my-2 list-disc pl-5" {...props} />,
	ol: (props: object) => <ol className="my-2 list-decimal pl-5" {...props} />,
	li: (props: object) => <li className="my-0.5" {...props} />,
	table: (props: object) => (
		<div className="my-3 overflow-x-auto">
			<table className="min-w-full border-collapse text-xs" {...props} />
		</div>
	),
	th: (props: object) => (
		<th
			className="border border-zinc-300 bg-zinc-50 px-2 py-1 text-left font-medium dark:border-zinc-600 dark:bg-zinc-800"
			{...props}
		/>
	),
	td: (props: object) => (
		<td
			className="border border-zinc-200 px-2 py-1 align-top dark:border-zinc-700"
			{...props}
		/>
	),
	pre: (props: object) => (
		<pre
			className="my-3 overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-100 dark:bg-black"
			{...props}
		/>
	),
	code: (props: object) => (
		<code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px] dark:bg-zinc-800" {...props} />
	),
	a: (props: object) => (
		<a
			className="text-[#5c9200] underline dark:text-[#a3e635]"
			target="_blank"
			rel="noreferrer"
			{...props}
		/>
	),
	img: (props: object) => (
		// eslint-disable-next-line @next/next/no-img-element -- parsed documents carry data: and /api asset URLs
		<img className="my-2 max-w-full" alt="" {...props} />
	),
	blockquote: (props: object) => (
		<blockquote
			className="my-2 border-l-2 border-zinc-300 pl-3 text-secondary dark:border-zinc-600 dark:text-zinc-400"
			{...props}
		/>
	),
	hr: (props: object) => <hr className="my-4 border-zinc-200 dark:border-zinc-700" {...props} />,
};

export const MarkdownContent = ({ markdown }: { markdown: string }) => (
	<ReactMarkdown
		remarkPlugins={[remarkGfm]}
		rehypePlugins={[rehypeRaw, rehypeSanitize]}
		components={MARKDOWN_COMPONENTS}
	>
		{markdown}
	</ReactMarkdown>
);
