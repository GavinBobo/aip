// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { Column, Database, Schema, Table } from '@/types/datasources';
import { DataModels } from '@/enums/datasources';
import { Icon, IconName } from '@/common/icons';
import { datasources } from '@/api/datasources';
import { catalogNodeInfo } from '@/components/dataPage/catalog-node-utils';
import { getTableType } from '@/components/dataPage/get-table-type';
import { sourceGroupRank, sourceKind, type SourceGroup } from '@/components/dataPage/source-type';
import { catalogPathFromFocusId } from '@/lib/data/data-catalog-path';
import { t } from '@/i18n';
import { splitId } from '@/lib/data/catalog-ids';
import { Text } from '@/common/Text';
import { TextVariant } from '@/enums/text';
import {
	catalogStructureFingerprint,
	mergeColumnsIntoTable,
	mergeDatabaseCatalog,
	mergeSchemasIntoDatabase,
	mergeTablesIntoSchema,
} from '@/lib/data/datasource-tree-merge';

function scheduleTreeDataNotify(
	onTreeDataUpdated: ((dbs: Database[]) => void) | undefined,
	next: Database[],
): void {
	if (!onTreeDataUpdated) return;
	queueMicrotask(() => {
		onTreeDataUpdated(next);
	});
}

// True only for a *descendant* of the node. Focus on the node itself must not
// count: a branch that owns the focus has to be able to stay collapsed.
function focusIsInsideSubtree(nodeFocusPath: string, focusId: string | undefined): boolean {
	return focusId != null && focusId.startsWith(`${nodeFocusPath}|`);
}

// Remembers which nodes the user has explicitly expanded/collapsed, so a
// page refresh restores the tree as they left it instead of only ever
// re-deriving it from the `focus` URL param (which stays put on collapse).
const OPEN_STATE_STORAGE_KEY = 'auto_ontology.dataTree.openState';
// Which connector-type groups the user folded away.
const COLLAPSED_GROUPS_STORAGE_KEY = 'auto_ontology.dataTree.collapsedGroups';

function readPersistedOpenState(): Record<string, boolean> {
	if (typeof window === 'undefined') return {};
	try {
		const raw = window.localStorage.getItem(OPEN_STATE_STORAGE_KEY);
		return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
	} catch {
		return {};
	}
}

function writePersistedOpenState(nodeId: string, open: boolean): void {
	if (typeof window === 'undefined') return;
	try {
		const state = readPersistedOpenState();
		state[nodeId] = open;
		window.localStorage.setItem(OPEN_STATE_STORAGE_KEY, JSON.stringify(state));
	} catch {
		// Storage can be unavailable (private mode, quota) — expand state
		// just won't survive a refresh, which is a harmless degradation.
	}
}

// Collapsing a branch hides its whole subtree, so any previously-remembered
// "expanded" state further down would otherwise silently resurface the next
// time this branch is opened again. Force every descendant closed so
// re-expanding starts fresh, the same as the first time the page was opened.
function collapsePersistedDescendants(nodeId: string): void {
	if (typeof window === 'undefined') return;
	try {
		const state = readPersistedOpenState();
		const prefix = `${nodeId}|`;
		let changed = false;
		Object.keys(state).forEach((key) => {
			if (key.startsWith(prefix) && state[key] !== false) {
				state[key] = false;
				changed = true;
			}
		});
		if (changed) window.localStorage.setItem(OPEN_STATE_STORAGE_KEY, JSON.stringify(state));
	} catch {
		// Storage can be unavailable — same harmless degradation as above.
	}
}

function readCollapsedGroups(): SourceGroup[] {
	if (typeof window === 'undefined') return [];
	try {
		const raw = window.localStorage.getItem(COLLAPSED_GROUPS_STORAGE_KEY);
		const parsed: unknown = raw ? JSON.parse(raw) : [];
		return Array.isArray(parsed)
			? parsed.filter((value): value is SourceGroup => typeof value === 'string')
			: [];
	} catch {
		return [];
	}
}

function writeCollapsedGroups(groups: SourceGroup[]): void {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(COLLAPSED_GROUPS_STORAGE_KEY, JSON.stringify(groups));
	} catch {
		// Storage unavailable — the fold just will not survive a refresh.
	}
}

function useOpenBranch(
	nodeId: string,
	focusInsideSubtree: boolean,
	selectedId: string | undefined,
	defaultOpen: boolean,
) {
	// Deliberately starts from `defaultOpen` rather than reading
	// `readPersistedOpenState()` directly here — this initializer runs
	// during SSR too, where `window` (and so any persisted state) is always
	// unavailable, so reading it here would make the very first client
	// render disagree with the server-rendered HTML and force React to
	// reconcile a hydration mismatch. Persisted state is applied once below
	// instead, using the same "adjust state during rendering" pattern
	// `prevSelectedId` already uses further down — React re-renders before
	// committing/hydrating, so the corrected value is what actually reaches
	// the DOM, never a mismatch.
	const [open, setOpenState] = useState(() => focusInsideSubtree || defaultOpen);
	const [hasAppliedPersisted, setHasAppliedPersisted] = useState(false);
	if (!hasAppliedPersisted) {
		setHasAppliedPersisted(true);
		const persisted = readPersistedOpenState()[nodeId];
		if (persisted !== undefined) setOpenState(focusInsideSubtree || persisted);
	}
	const [prevSelectedId, setPrevSelectedId] = useState(selectedId);
	if (selectedId !== prevSelectedId) {
		setPrevSelectedId(selectedId);
		// Reveal a descendant the focus moved to (deep link, detail panel). Since
		// clicking a row also moves the focus onto that row, collapsing never
		// leaves the focus below and never re-expands this branch.
		if (focusInsideSubtree) setOpenState(true);
	}
	const setOpen = useCallback(
		(value: boolean | ((prev: boolean) => boolean)) => {
			setOpenState((prev) => {
				const next = typeof value === 'function' ? value(prev) : value;
				writePersistedOpenState(nodeId, next);
				if (!next) collapsePersistedDescendants(nodeId);
				return next;
			});
		},
		[nodeId],
	);
	return [open, setOpen] as const;
}

export type DataTreeProps = {
	initialDatabases: Database[];
	selectedId?: string;
	pathBase?: string;
	className?: string;
	onTreeDataUpdated?: (databases: Database[]) => void;
};

function rowClassName(selected: boolean) {
	return `flex min-h-9 cursor-pointer items-center gap-1 rounded-lg text-left text-sm no-underline transition-colors ${
		selected
			? 'bg-[#76b900]/15 font-medium text-heading shadow-sm ring-1 ring-[#76b900]/30 dark:text-zinc-100'
			: 'text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70'
	}`;
}

function Row({
	depth,
	open,
	onToggle,
	hasChildren,
	loading,
	name,
	icon,
	title,
	selected,
	href,
	badge,
	onClick,
	onActivateBranch,
	onChevronFocusSync,
}: {
	depth: number;
	/** Only meaningful when `hasChildren` — leaf rows can omit it. */
	open?: boolean;
	/** Only called when `hasChildren` — leaf rows can omit it. */
	onToggle?: () => void;
	hasChildren: boolean;
	loading?: boolean;
	name: string;
	icon?: IconName;
	title?: string;
	selected: boolean;
	href?: string;
	/** Small trailing label (e.g. the source type on a database row). */
	badge?: string;
	onClick?: () => void;
	/** Branch rows: toggle expand/collapse and move `focus` onto this node. */
	onActivateBranch?: () => void;
	/** After chevron toggles expand/collapse, sync `focus` to this node (same as row select). */
	onChevronFocusSync?: () => void;
}) {
	const pad = 12 + depth * 12;
	const style = { paddingLeft: pad, paddingRight: 12 };

	const nodeIconEl = icon ? (
		<span className="inline-flex shrink-0" title={title} aria-hidden>
			<Icon name={icon} className="h-4 w-4 text-secondary dark:text-zinc-400" />
		</span>
	) : null;

	const chevron = (
		<span
			role="button"
			tabIndex={0}
			className="inline-flex w-4 shrink-0 cursor-pointer items-center justify-center rounded text-[10px] text-secondary hover:bg-zinc-200/80 dark:hover:bg-zinc-700/80"
			onClick={(e) => {
				e.stopPropagation();
				if (!hasChildren) return;
				onToggle?.();
				onChevronFocusSync?.();
			}}
			onKeyDown={(e) => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					e.stopPropagation();
					if (!hasChildren) return;
					onToggle?.();
					onChevronFocusSync?.();
				}
			}}
		>
			{loading ? '…' : hasChildren ? (open ? '▼' : '▶') : '·'}
		</span>
	);

	const nameEl = <Text text={name} variant={TextVariant.Strong} fill />;
	const badgeEl = badge ? (
		<span className="shrink-0 rounded-full border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
			{badge}
		</span>
	) : null;

	const inner = (
		<>
			{chevron}
			{nodeIconEl}
			{nameEl}
			{badgeEl}
		</>
	);

	if (href && !hasChildren) {
		return (
			<Link href={href} prefetch={false} className={rowClassName(selected)} style={style}>
				{inner}
			</Link>
		);
	}

	return (
		<div
			className={rowClassName(selected)}
			style={style}
			onClick={() => {
				if (onActivateBranch) {
					onActivateBranch();
				} else if (hasChildren) {
					onToggle?.();
				}
				onClick?.();
			}}
		>
			{inner}
		</div>
	);
}

function ColumnBlock({
	depth,
	column,
	columnFocusPath,
	selectedId,
	pathBase,
}: {
	depth: number;
	column: Column;
	columnFocusPath: string;
	selectedId?: string;
	pathBase: string;
}) {
	return (
		<div>
			<Row
				depth={depth}
				hasChildren={false}
				name={column.column_name}
				icon={catalogNodeInfo[DataModels.COLUMN].icon}
				title={t(catalogNodeInfo[DataModels.COLUMN].title)}
				selected={selectedId === columnFocusPath}
				href={catalogPathFromFocusId(columnFocusPath, pathBase)}
			/>
		</div>
	);
}

function TableBlock({
	depth,
	table,
	tableFocusPath,
	tableLoadRef,
	selectedId,
	pathBase,
	onLoadColumns,
}: {
	depth: number;
	table: Table;
	/** `dbId|schemaId|tableId` for URLs, selection, and lazy column fetch. */
	tableFocusPath: string;
	/** Same as ``tableFocusPath``; passed to ``onLoadColumns`` for column fetch. */
	tableLoadRef: string;
	selectedId?: string;
	pathBase: string;
	onLoadColumns: (tableCompoundId: string) => void;
}) {
	const router = useRouter();
	const focusInsideTable = focusIsInsideSubtree(tableFocusPath, selectedId);
	const [open, setOpen] = useOpenBranch(tableFocusPath, focusInsideTable, selectedId, false);
	const fetchedOnce = useRef(false);
	const syncTableFocus = useCallback(() => {
		router.replace(catalogPathFromFocusId(tableFocusPath, pathBase), { scroll: false });
	}, [router, pathBase, tableFocusPath]);
	const activateTable = useCallback(() => {
		setOpen((o) => !o);
		syncTableFocus();
	}, [setOpen, syncTableFocus]);

	const hasChildren = table.columns_count > 0;

	useEffect(() => {
		if (open && !fetchedOnce.current && table.columns.length === 0 && table.columns_count > 0) {
			fetchedOnce.current = true;
			onLoadColumns(tableLoadRef);
		}
	}, [open, table.columns.length, table.columns_count, tableLoadRef, onLoadColumns]);

	const loading = open && table.columns.length === 0 && table.columns_count > 0;
	const tableInfo = catalogNodeInfo[getTableType(table.table_type)];

	return (
		<div className="flex flex-col gap-y-1">
			<Row
				depth={depth}
				open={open}
				onToggle={() => setOpen((o) => !o)}
				hasChildren={hasChildren}
				loading={loading}
				name={table.name}
				icon={tableInfo.icon}
				title={tableInfo.title}
				selected={selectedId === tableFocusPath}
				href={hasChildren ? undefined : catalogPathFromFocusId(tableFocusPath, pathBase)}
				onActivateBranch={hasChildren ? activateTable : undefined}
				onChevronFocusSync={hasChildren ? syncTableFocus : undefined}
			/>
			{open && table.columns.length > 0
				? table.columns.map((col) => (
						<ColumnBlock
							key={col.id}
							depth={depth + 1}
							column={col}
							columnFocusPath={`${tableFocusPath}|${col.id}`}
							selectedId={selectedId}
							pathBase={pathBase}
						/>
					))
				: null}
		</div>
	);
}

function SchemaBlock({
	depth,
	databaseId,
	schema,
	selectedId,
	pathBase,
	onLoadColumns,
	onLoadTables,
}: {
	depth: number;
	databaseId: string;
	schema: Schema;
	selectedId?: string;
	pathBase: string;
	onLoadColumns: (tableCompoundId: string) => void;
	onLoadTables: (schemaCompoundId: string) => Promise<void>;
}) {
	const router = useRouter();
	const schemaFocusPath = `${databaseId}|${schema.id}`;
	const schemaLoadRef = schemaFocusPath;
	const focusInsideSchema = focusIsInsideSubtree(schemaFocusPath, selectedId);
	const [open, setOpen] = useOpenBranch(schemaFocusPath, focusInsideSchema, selectedId, false);
	const hasChildren = (schema.tables_count ?? 0) > 0;
	const [loadingTables, setLoadingTables] = useState(false);
	const syncSchemaFocus = useCallback(() => {
		router.replace(catalogPathFromFocusId(schemaFocusPath, pathBase), { scroll: false });
	}, [router, pathBase, schemaFocusPath]);
	const activateSchemaBranch = useCallback(() => {
		setOpen((o) => !o);
		syncSchemaFocus();
	}, [setOpen, syncSchemaFocus]);

	useEffect(() => {
		if (!open || schema.tables.length > 0 || (schema.tables_count ?? 0) === 0) return;
		let cancelled = false;
		void (async () => {
			await Promise.resolve();
			if (cancelled) return;
			setLoadingTables(true);
			try {
				await onLoadTables(schemaLoadRef);
			} finally {
				if (!cancelled) setLoadingTables(false);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [open, schemaLoadRef, schema.tables_count, schema.tables.length, onLoadTables]);

	return (
		<div className="flex flex-col gap-y-1">
			<Row
				depth={depth}
				open={open}
				onToggle={() => setOpen((o) => !o)}
				hasChildren={hasChildren}
				loading={loadingTables}
				name={schema.schema_name}
				icon={catalogNodeInfo[DataModels.SCHEMA].icon}
				title={t(catalogNodeInfo[DataModels.SCHEMA].title)}
				selected={selectedId === schemaFocusPath}
				href={hasChildren ? undefined : catalogPathFromFocusId(schemaFocusPath, pathBase)}
				onActivateBranch={hasChildren ? activateSchemaBranch : undefined}
				onChevronFocusSync={hasChildren ? syncSchemaFocus : undefined}
			/>
			{open && hasChildren
				? schema.tables.map((t) => {
						const tableFocusPath = `${schemaFocusPath}|${t.id}`;
						return (
							<TableBlock
								key={t.id}
								depth={depth + 1}
								table={t}
								tableFocusPath={tableFocusPath}
								tableLoadRef={tableFocusPath}
								selectedId={selectedId}
								pathBase={pathBase}
								onLoadColumns={onLoadColumns}
							/>
						);
					})
				: null}
		</div>
	);
}

function DatabaseBlock({
	database,
	selectedId,
	pathBase,
	onLoadColumns,
	onLoadSchemas,
	onLoadTables,
}: {
	database: Database;
	selectedId?: string;
	pathBase: string;
	onLoadColumns: (tableCompoundId: string) => void;
	onLoadSchemas: (dbId: string) => Promise<void>;
	onLoadTables: (schemaCompoundId: string) => Promise<void>;
}) {
	const router = useRouter();
	const focusInsideDatabase = focusIsInsideSubtree(database.id, selectedId);
	const [open, setOpen] = useOpenBranch(database.id, focusInsideDatabase, selectedId, false);
	const hasChildren = database.schemas.length > 0 || !open;
	const [loadingSchemas, setLoadingSchemas] = useState(false);
	const syncDatabaseFocus = useCallback(() => {
		router.replace(catalogPathFromFocusId(database.id, pathBase), { scroll: false });
	}, [router, pathBase, database.id]);
	const activateDatabaseBranch = useCallback(() => {
		setOpen((o) => !o);
		syncDatabaseFocus();
	}, [setOpen, syncDatabaseFocus]);

	useEffect(() => {
		if (!open || database.schemas.length > 0) return;
		let cancelled = false;
		void (async () => {
			await Promise.resolve();
			if (cancelled) return;
			setLoadingSchemas(true);
			try {
				await onLoadSchemas(database.id);
			} finally {
				if (!cancelled) setLoadingSchemas(false);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [open, database.id, database.schemas.length, onLoadSchemas]);

	return (
		<div className="flex flex-col gap-y-1">
			<Row
				depth={0}
				open={open}
				onToggle={() => setOpen((o) => !o)}
				hasChildren={hasChildren}
				loading={loadingSchemas}
				name={database.name}
				icon={catalogNodeInfo[DataModels.DB].icon}
				title={t(catalogNodeInfo[DataModels.DB].title)}
				badge={t(sourceKind(database.source_type).label)}
				selected={selectedId === database.id}
				href={undefined}
				onActivateBranch={activateDatabaseBranch}
				onChevronFocusSync={hasChildren ? syncDatabaseFocus : undefined}
			/>
			{open && hasChildren
				? database.schemas.map((s) => (
						<SchemaBlock
							key={s.id}
							depth={1}
							databaseId={database.id}
							schema={s}
							selectedId={selectedId}
							pathBase={pathBase}
							onLoadColumns={onLoadColumns}
							onLoadTables={onLoadTables}
						/>
					))
				: null}
		</div>
	);
}

/**
 * One connector-type group, foldable from its bordered header.
 *
 * The databases inside keep their own state while folded: only rendering is
 * skipped, so unfolding does not re-fetch schemas or lose expanded branches.
 */
function DataGroup({
	group,
	label,
	icon,
	count,
	collapsed,
	onToggle,
	children,
}: {
	group: SourceGroup;
	label: string;
	icon: IconName;
	count: number;
	collapsed: boolean;
	onToggle: () => void;
	children: ReactNode;
}) {
	return (
		<section
			className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-900"
			data-group={group}
		>
			<button
				type="button"
				onClick={onToggle}
				aria-expanded={!collapsed}
				className="flex w-full items-center gap-2 border-l-2 border-[#76b900]/70 bg-zinc-50/80 px-2.5 py-2 text-left transition-colors hover:bg-[#76b900]/10 dark:bg-zinc-800/60 dark:hover:bg-[#76b900]/10"
			>
				<span
					className="w-3 shrink-0 text-[9px] text-secondary dark:text-zinc-400"
					aria-hidden
				>
					{collapsed ? '▶' : '▼'}
				</span>
				<Icon
					name={icon}
					className="h-3.5 w-3.5 shrink-0 text-body dark:text-zinc-300"
					aria-hidden
				/>
				<span className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-heading dark:text-zinc-200">
					{t(label)}
				</span>
				<span className="shrink-0 rounded-full border border-zinc-300 bg-white px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-secondary dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
					{count}
				</span>
			</button>
			{/*
			 * Hidden with CSS rather than unmounted: the databases keep their
			 * lazy-load effects alive, so a table reached by a deep link still
			 * resolves (and the detail page's preview still has its branch).
			 */}
			<div
				className={
					collapsed
						? 'hidden'
						: 'flex flex-col gap-y-1 border-t border-zinc-200/80 px-1.5 py-1.5 dark:border-zinc-700/80'
				}
			>
				{children}
			</div>
		</section>
	);
}

export function DataTree({
	initialDatabases,
	selectedId,
	pathBase = '/data',
	className = '',
	onTreeDataUpdated,
}: DataTreeProps) {
	const [databases, setDatabases] = useState<Database[]>(initialDatabases);
	const catalogFpRef = useRef('');
	const [collapsedGroups, setCollapsedGroups] = useState<SourceGroup[]>([]);
	// Persisted fold state is applied during the first render rather than from
	// an effect: `window` is unavailable during SSR, so an effect would make the
	// hydrated tree flash open and then fold (and setState-in-effect is what the
	// React Compiler lint flags). React re-renders before committing, so the
	// corrected value is what reaches the DOM.
	const [hasAppliedGroups, setHasAppliedGroups] = useState(false);
	if (!hasAppliedGroups) {
		setHasAppliedGroups(true);
		const persisted = readCollapsedGroups();
		if (persisted.length > 0) setCollapsedGroups(persisted);
	}

	const toggleGroup = useCallback((group: SourceGroup) => {
		setCollapsedGroups((previous) => {
			const next = previous.includes(group)
				? previous.filter((value) => value !== group)
				: [...previous, group];
			writeCollapsedGroups(next);
			return next;
		});
	}, []);

	useEffect(() => {
		const fp = catalogStructureFingerprint(initialDatabases);
		if (fp === catalogFpRef.current) return;
		catalogFpRef.current = fp;
		queueMicrotask(() => {
			setDatabases((prev) => mergeDatabaseCatalog(prev, initialDatabases));
		});
	}, [initialDatabases]);

	const loadSchemasForDatabase = useCallback(
		async (dbId: string) => {
			const res = await datasources.getSchemasForDatabase(dbId);
			if (res.error || !res.data) return;
			setDatabases((prev) => {
				const next = mergeSchemasIntoDatabase(prev, dbId, res.data);
				scheduleTreeDataNotify(onTreeDataUpdated, next);
				return next;
			});
		},
		[onTreeDataUpdated],
	);

	const loadTablesForSchema = useCallback(
		async (schemaCompoundId: string) => {
			const [, schemaElemId] = splitId(schemaCompoundId, 2);
			const res = await datasources.getTablesForSchema(schemaElemId);
			if (res.error || !res.data) return;
			setDatabases((prev) => {
				const next = mergeTablesIntoSchema(prev, schemaElemId, res.data);
				scheduleTreeDataNotify(onTreeDataUpdated, next);
				return next;
			});
		},
		[onTreeDataUpdated],
	);

	const loadTableColumns = useCallback(
		async (tableCompoundId: string) => {
			const [, , tableElemId] = splitId(tableCompoundId, 3);
			const res = await datasources.getColumnsForTable(tableElemId);
			if (res.error || !res.data) return;
			setDatabases((prev) => {
				const next = mergeColumnsIntoTable(prev, tableElemId, res.data);
				scheduleTreeDataNotify(onTreeDataUpdated, next);
				return next;
			});
		},
		[onTreeDataUpdated],
	);

	// Group by connector type — Excel/CSV, REST API, PostgreSQL, MySQL, and so
	// on — rather than folding every warehouse into one generic "Databases"
	// bucket. Order inside a group is the API's (database name), so nothing
	// reshuffles between loads.
	const groups = useMemo(() => {
		const byGroup = new Map<
			SourceGroup,
			{ kind: ReturnType<typeof sourceKind>; members: Database[] }
		>();
		for (const database of databases) {
			const kind = sourceKind(database.source_type);
			const bucket = byGroup.get(kind.group);
			if (bucket) bucket.members.push(database);
			else byGroup.set(kind.group, { kind, members: [database] });
		}
		return [...byGroup.entries()].sort(([a, left], [b, right]) => {
			const byRank = sourceGroupRank(a) - sourceGroupRank(b);
			return byRank !== 0 ? byRank : left.kind.label.localeCompare(right.kind.label);
		});
	}, [databases]);

	return (
		<nav
			className={`flex min-h-0 flex-1 flex-col gap-y-2 overflow-y-auto px-3 py-2 sm:px-4 ${className}`}
			aria-label={t('Datasource tree')}
		>
			{groups.map(([group, { kind, members }]) => (
				<DataGroup
					key={group}
					group={group}
					label={kind.label}
					icon={kind.icon}
					count={members.length}
					collapsed={collapsedGroups.includes(group)}
					onToggle={() => toggleGroup(group)}
				>
					{members.map((database) => (
						<DatabaseBlock
							key={database.id}
							database={database}
							selectedId={selectedId}
							pathBase={pathBase}
							onLoadColumns={loadTableColumns}
							onLoadSchemas={loadSchemasForDatabase}
							onLoadTables={loadTablesForSchema}
						/>
					))}
				</DataGroup>
			))}
		</nav>
	);
}

export default DataTree;
