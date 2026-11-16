// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { t } from '@/i18n';
import { activeSectionHref } from '@/lib/parsingNav';

type NavItem = {
	label: string;
	href: string;
};

const ITEMS: NavItem[] = [
	{ label: 'Parsing Instances', href: '/parsing' },
	{ label: 'New Batch Task', href: '/parsing/batch' },
];

const rowClassName = (selected: boolean): string =>
	`flex min-h-9 items-center rounded-lg px-3 text-sm no-underline transition-colors ${
		selected
			? 'bg-[#76b900]/15 font-medium text-heading shadow-sm ring-1 ring-[#76b900]/30 dark:text-zinc-100'
			: 'text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70'
	}`;

/** The 文档解析 section's second-level menu, styled like Settings'. */
export const ParsingNav = () => {
	const pathname = usePathname();
	// The most specific href wins, so `/parsing/batch` does not also select the
	// `/parsing` entry it is nested under.
	const activeHref = activeSectionHref(
		pathname,
		ITEMS.map((item) => item.href),
	);

	return (
		<nav
			className="flex min-h-0 flex-1 flex-col gap-y-1 overflow-y-auto px-3 py-2 sm:px-4"
			aria-label={t('Document parsing sections')}
		>
			{ITEMS.map((item) => {
				const selected = item.href === activeHref;
				return (
					<Link
						key={item.href}
						href={item.href}
						className={rowClassName(selected)}
						aria-current={selected ? 'page' : undefined}
					>
						{t(item.label)}
					</Link>
				);
			})}
		</nav>
	);
};
