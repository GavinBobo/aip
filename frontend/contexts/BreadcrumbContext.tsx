// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useState,
	type ReactNode,
} from 'react';
import { usePathname } from 'next/navigation';
import type { BreadcrumbItem } from '@/common/Breadcrumbs';
import { t } from '@/i18n';

const SECTION_LABELS: Record<string, string> = {
	'/chat': 'Chat',
	'/discovery': 'Discovery',
	'/terms': 'Terms',
	'/analysis': 'Analysis',
	'/exploration': 'Exploration',
	'/data': 'All Data',
	'/analytics': 'Analytics',
	'/settings': 'Settings',
};

const SETTINGS_SECTION_LABELS: Record<string, string> = {
	connections: 'Connections',
	zones: 'Zones',
	tags: 'Tags',
	rules: 'Rules',
	'semantic-input': 'Semantic Input',
	'semantic-compilation': 'Semantic Compilation',
	pii: 'PII Settings',
	'agent-settings': 'Agent Settings',
	users: 'Users',
	sso: 'Single Sign-On',
	'import-export': 'Import / Export',
	'model-settings': 'Model Settings',
	parsing: 'Document Parsing',
};

const EMPTY_TRAIL: BreadcrumbItem[] = [];

const sectionForPath = (path: string): BreadcrumbItem | null => {
	const href = Object.keys(SECTION_LABELS).find(
		(prefix) => path === prefix || path.startsWith(`${prefix}/`),
	);
	const label = href == null ? undefined : t(SECTION_LABELS[href]);
	return href != null && label != null ? { label, href } : null;
};

const crumbsForPath = (path: string): BreadcrumbItem[] => {
	const section = sectionForPath(path);
	if (section == null) return EMPTY_TRAIL;
	if (section.href !== '/settings') return [section];

	const slug = path.split('/')[2];
	const label = slug == null ? undefined : t(SETTINGS_SECTION_LABELS[slug]);
	return label == null ? [section] : [section, { label, href: `/settings/${slug}` }];
};

const trailKey = (items: BreadcrumbItem[]): string =>
	items.map((item) => `${item.label}\u0000${item.href ?? ''}`).join('\u0001');

type BreadcrumbContextValue = {
	items: BreadcrumbItem[];
	setTrail: (items: BreadcrumbItem[]) => void;
	rightSlot: ReactNode;
	setRightSlot: (node: ReactNode) => void;
};

const BreadcrumbContext = createContext<BreadcrumbContextValue>({
	items: EMPTY_TRAIL,
	setTrail: () => {},
	rightSlot: null,
	setRightSlot: () => {},
});

export const BreadcrumbProvider = ({ children }: { children: ReactNode }) => {
	const pathname = usePathname();
	const [prevPath, setPrevPath] = useState<string | null>(null);
	const [routeCrumbs, setRouteCrumbs] = useState<BreadcrumbItem[]>(EMPTY_TRAIL);
	const [trail, setTrailRaw] = useState<BreadcrumbItem[]>(EMPTY_TRAIL);
	const [rightSlot, setRightSlotRaw] = useState<ReactNode>(null);

	const setRightSlot = useCallback((node: ReactNode) => setRightSlotRaw(node), []);

	const setTrail = useCallback((next: BreadcrumbItem[]) => {
		setTrailRaw((prev) => (trailKey(prev) === trailKey(next) ? prev : next));
	}, []);

	if (pathname !== prevPath) {
		// A breadcrumb describes where this route sits, not how the user got
		// here. Top-level sections (Discovery, Terms, Analysis, …) are siblings:
		// treating the previously visited one as the current route's parent
		// produced false or backwards trails such as "Terms > Discovery".
		// Deeper detail crumbs are supplied separately by useBreadcrumbTrail.
		setRouteCrumbs(crumbsForPath(pathname));
		setTrailRaw(EMPTY_TRAIL);
		setPrevPath(pathname);
	}

	const items = useMemo(
		() => (trail.length === 0 ? routeCrumbs : [...routeCrumbs, ...trail]),
		[routeCrumbs, trail],
	);

	const value = useMemo(
		() => ({ items, setTrail, rightSlot, setRightSlot }),
		[items, setTrail, rightSlot, setRightSlot],
	);

	return <BreadcrumbContext.Provider value={value}>{children}</BreadcrumbContext.Provider>;
};

export const useBreadcrumbs = () => useContext(BreadcrumbContext);

export const useBreadcrumbTrail = (items: BreadcrumbItem[]) => {
	const { setTrail } = useBreadcrumbs();

	useEffect(() => {
		setTrail(items);
	});

	useEffect(() => () => setTrail(EMPTY_TRAIL), [setTrail]);
};
