// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { usePathname } from 'next/navigation';
import { Icon, IconName } from '@/common/icons';
import { Breadcrumbs } from '@/common/Breadcrumbs';
import { GlobalSearch } from '@/common/GlobalSearch';
import { UserMenu } from '@/common/UserMenu';
import { useBreadcrumbs } from '@/contexts/BreadcrumbContext';
import { LanguageToggle } from '@/i18n/LanguageToggle';

export const AppTopBar = ({ version }: { version?: string }) => {
	const { items, rightSlot } = useBreadcrumbs();
	const pathname = usePathname();
	// The chat page renders a floating sidebar toggle at the top-left below the
	// lg breakpoint; keep the brand and breadcrumbs clear of it.
	const hasFloatingToggle = pathname.startsWith('/chat');

	return (
		<header
			className={`flex h-[52px] shrink-0 items-center border-b border-zinc-200 bg-white pr-[40px] dark:border-zinc-800 dark:bg-zinc-950 ${
				hasFloatingToggle ? 'pl-16 lg:pl-4' : 'pl-4'
			}`}
		>
			<Icon name={IconName.NvidiaLogo} className="mr-3 h-5 w-5 shrink-0" />
			<Breadcrumbs items={items} />
			<div className="ml-auto flex items-center gap-3">
				{rightSlot ? <div className="flex items-center gap-2">{rightSlot}</div> : null}
				<GlobalSearch />
				<LanguageToggle />
				<UserMenu version={version} />
			</div>
		</header>
	);
};
