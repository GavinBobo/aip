// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { knowledgeApi, type KnowledgeNetwork } from '@/api/knowledge';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { t } from '@/i18n';

export const KnowledgeSidebar = () => {
	const pathname = usePathname();
	const [networks, setNetworks] = useState<KnowledgeNetwork[]>([]);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		let cancelled = false;
		knowledgeApi.listNetworks().then((response) => {
			if (cancelled) return;
			setLoading(false);
			if (!response.error && response.data) setNetworks(response.data);
		});
		return () => {
			cancelled = true;
		};
	}, [pathname]);

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex items-center justify-between px-4 py-3">
				<Link
					href="/knowledge"
					className="text-sm font-semibold tracking-tight text-heading no-underline dark:text-zinc-100"
				>
					{t('Knowledge Ontology')}
				</Link>
				<Link
					href="/knowledge?new=1"
					className="flex h-7 w-7 items-center justify-center rounded-md text-secondary transition-colors hover:bg-[#76b900]/10 hover:text-[#5e9400]"
					title={t('New knowledge network')}
					aria-label={t('New knowledge network')}
				>
					<Icon name={IconName.Plus} className="h-4 w-4" />
				</Link>
			</div>
			<nav
				className="flex min-h-0 flex-1 flex-col gap-y-1 overflow-y-auto px-3 pb-4"
				aria-label={t('Knowledge networks')}
			>
				{loading ? (
					<div className="flex justify-center py-6">
						<Spinner />
					</div>
				) : (
					<>
						<Link
							href="/knowledge"
							className={`flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm no-underline transition-colors ${
								pathname === '/knowledge'
									? 'bg-[#76b900]/15 font-medium text-heading ring-1 ring-[#76b900]/30'
									: 'text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70'
							}`}
						>
							<Icon name={IconName.Knowledge} className="h-4 w-4 shrink-0" />
							{t('All knowledge networks')}
						</Link>
						<div className="mt-3 px-3 text-[11px] font-semibold tracking-wide text-secondary uppercase">
							{t('Knowledge networks')}
						</div>
						{networks.length === 0 && (
							<p className="px-3 py-2 text-xs text-secondary">
								{t('No knowledge networks yet.')}
							</p>
						)}
						{networks.map((network) => {
							const href = `/knowledge/${encodeURIComponent(network.id)}`;
							const selected = pathname === href;
							return (
								<Link
									key={network.id}
									href={href}
									className={`group flex flex-col gap-0.5 rounded-lg px-3 py-2 text-sm no-underline transition-colors ${
										selected
											? 'bg-[#76b900]/15 font-medium text-heading ring-1 ring-[#76b900]/30'
											: 'text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70'
									}`}
								>
									<span className="flex items-center justify-between gap-2">
										<span className="truncate">{network.name}</span>
										<span className="shrink-0 text-[10px] text-secondary">
											{network.concept_count}
										</span>
									</span>
									<span className="truncate text-[11px] text-secondary">
										{network.domain || t('No domain')}
									</span>
								</Link>
							);
						})}
					</>
				)}
			</nav>
		</div>
	);
};
