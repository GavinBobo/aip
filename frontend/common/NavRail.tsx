// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Fragment, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icon, IconName } from '@/common/icons';
import { t } from '@/i18n';

type NavItem = {
	icon: IconName;
	href: string;
	label: string;
	adminOnly?: boolean;
	/** Pinned to the bottom of the rail, below a flexible gap. */
	pinned?: boolean;
	/** A divider after this item separates one functional group from the next. */
	dividerAfter?: boolean;
};

const navItems: NavItem[] = [
	{ icon: IconName.ChatBubble, href: '/chat', label: 'Chat', dividerAfter: true },
	{ icon: IconName.Discovery, href: '/discovery', label: 'Discovery' },
	{ icon: IconName.Terms, href: '/terms', label: 'Terms' },
	{ icon: IconName.ChartBar, href: '/analysis', label: 'Analysis' },
	{ icon: IconName.Exploration, href: '/exploration', label: 'Exploration' },
	{ icon: IconName.Schema, href: '/erd', label: 'ER Model' },
	{ icon: IconName.Database, href: '/data', label: 'Data', dividerAfter: true },
	// Parsing, the knowledge ontology and analytics sit at the end of the
	// scrolling list, above the pinned Settings entry.
	{
		icon: IconName.Spreadsheet,
		href: '/parsing',
		label: 'Document Parsing',
		adminOnly: true,
	},
	{
		icon: IconName.Knowledge,
		href: '/knowledge',
		label: 'Knowledge Ontology',
		dividerAfter: true,
	},
	{ icon: IconName.ChartLine, href: '/analytics', label: 'Analytics', adminOnly: true },
	// Settings is admin-only and now also contains Users and Single Sign-On
	// (see app/settings/*). Viewers don't see it.
	{
		icon: IconName.Settings,
		href: '/settings',
		label: 'Settings',
		adminOnly: true,
		pinned: true,
	},
];

export const NavRail = ({ isAdmin = false }: { isAdmin?: boolean }) => {
	const pathname = usePathname();
	const [isExpanded, setIsExpanded] = useState(false);
	const visibleItems = navItems.filter((item) => !item.adminOnly || isAdmin);
	// Settings is pinned to the bottom of the rail, so it is rendered after the
	// spacer rather than in document order.
	const scrollItems = visibleItems.filter((item) => !item.pinned);
	const pinnedItems = visibleItems.filter((item) => item.pinned);

	const renderItem = (item: NavItem, showDivider = false) => {
		const isActive = pathname.startsWith(item.href);

		return (
			<Fragment key={item.href}>
				<Link
					href={item.href}
					title={isExpanded ? undefined : t(item.label)}
					className={`flex h-9 shrink-0 items-center gap-3 rounded-lg transition-colors ${
						isExpanded ? 'w-full px-2' : 'w-9 justify-center'
					} ${
						isActive
							? 'bg-[#76b900]/15 text-[#76b900]'
							: 'text-body hover:bg-zinc-100 hover:text-heading dark:hover:bg-zinc-800 dark:hover:text-zinc-200'
					}`}
				>
					<Icon name={item.icon} className="h-5 w-5 shrink-0" />
					{isExpanded && (
						<span className="truncate text-sm font-medium whitespace-nowrap">
							{t(item.label)}
						</span>
					)}
				</Link>
				{item.dividerAfter && showDivider ? (
					<div
						aria-hidden="true"
						className={`h-px shrink-0 bg-zinc-300 dark:bg-zinc-700 ${
							isExpanded ? 'mx-1 self-stretch' : 'w-6'
						}`}
					/>
				) : null}
			</Fragment>
		);
	};

	return (
		<nav className="relative h-full w-12 shrink-0 border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
			<div
				onMouseEnter={() => setIsExpanded(true)}
				onMouseLeave={() => setIsExpanded(false)}
				className={`absolute inset-y-0 left-0 flex flex-col overflow-hidden bg-white py-3 transition-[width] duration-200 ease-out dark:bg-zinc-950 ${
					isExpanded
						? 'z-30 w-56 border-r border-zinc-200 shadow-lg dark:border-zinc-800'
						: 'w-full'
				}`}
			>
				<div
					className={`flex flex-1 flex-col gap-2 ${isExpanded ? 'px-1.5' : 'items-center'}`}
				>
					{scrollItems.map((item, index) =>
						renderItem(item, index < scrollItems.length - 1),
					)}
					{pinnedItems.length > 0 && (
						<div className="mt-auto flex flex-col gap-2 pt-2">
							{pinnedItems.map((item) => renderItem(item))}
						</div>
					)}
				</div>
			</div>
		</nav>
	);
};
