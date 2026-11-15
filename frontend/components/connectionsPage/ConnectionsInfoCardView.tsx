// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo, useState } from 'react';
import { ConnectionInfoCard } from '@/components/connectionsPage/ConnectionInfoCard';
import { connectionKind, connectionKindRank } from '@/components/connectionsPage/connection-kind';
import { EmptyState } from '@/common/EmptyState';
import { t } from '@/i18n';
import { Icon, IconName } from '@/common/icons';
import { SkeletonCard } from '@/common/Skeleton';
import { EmptyStateVariant } from '@/enums/emptyState';
import { ConnectionType } from '@/enums/connection';
import type { Connection } from '@/types/connection';

type ConnectionsInfoCardViewProps = {
	connections: Connection[];
	loading?: boolean;
	onEdit?: (connection: Connection) => void;
	onDelete?: (databaseName: string) => void;
	onRefresh?: (databaseName: string) => void;
	refreshPending?: string | null;
	onSsoFederationChange?: (databaseName: string, enabled: boolean) => void;
	/** Database name whose SSO-federation request is currently in flight. */
	ssoFederationPending?: string | null;
};

export const ConnectionsInfoCardView = ({
	connections,
	loading = false,
	onEdit,
	onDelete,
	onRefresh,
	refreshPending = null,
	onSsoFederationChange,
	ssoFederationPending = null,
}: ConnectionsInfoCardViewProps) => {
	const [collapsedGroups, setCollapsedGroups] = useState<ConnectionType[]>([]);

	const groups = useMemo(() => {
		const byType = new Map<ConnectionType, Connection[]>();
		for (const connection of connections) {
			const type = connection.connection.type;
			const bucket = byType.get(type);
			if (bucket) bucket.push(connection);
			else byType.set(type, [connection]);
		}
		return [...byType.entries()].sort(([a], [b]) => {
			const byRank = connectionKindRank(a) - connectionKindRank(b);
			return byRank !== 0
				? byRank
				: connectionKind(a).label.localeCompare(connectionKind(b).label);
		});
	}, [connections]);

	const toggleGroup = (type: ConnectionType) => {
		setCollapsedGroups((previous) =>
			previous.includes(type)
				? previous.filter((value) => value !== type)
				: [...previous, type],
		);
	};

	if (loading) {
		return (
			<div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
				{Array.from({ length: 9 }, (_, i) => (
					<SkeletonCard key={i} className="min-h-[148px]" />
				))}
			</div>
		);
	}

	if (connections.length === 0) {
		return (
			<EmptyState
				variant={EmptyStateVariant.Borderless}
				icon={IconName.Connection}
				title={t('No Results')}
			/>
		);
	}

	return (
		<div className="flex w-full flex-col gap-3">
			{groups.map(([type, members]) => {
				const kind = connectionKind(type);
				const collapsed = collapsedGroups.includes(type);
				return (
					<section
						key={type}
						className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-900"
					>
						<button
							type="button"
							onClick={() => toggleGroup(type)}
							aria-expanded={!collapsed}
							className="flex w-full items-center gap-2 border-l-2 border-[#76b900]/70 bg-zinc-50/80 px-3 py-2 text-left transition-colors hover:bg-[#76b900]/10 dark:bg-zinc-800/60 dark:hover:bg-[#76b900]/10"
						>
							<span
								className="w-3 shrink-0 text-[9px] text-secondary dark:text-zinc-400"
								aria-hidden
							>
								{collapsed ? '▶' : '▼'}
							</span>
							<Icon
								name={kind.icon}
								className="h-4 w-4 shrink-0 text-body dark:text-zinc-300"
							/>
							<span className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-heading dark:text-zinc-200">
								{t(kind.label)}
							</span>
							<span className="shrink-0 rounded-full border border-zinc-300 bg-white px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-secondary dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
								{members.length}
							</span>
						</button>
						{!collapsed && (
							<div className="grid w-full grid-cols-1 gap-3 border-t border-zinc-200/80 p-3 sm:grid-cols-2 lg:grid-cols-3 dark:border-zinc-700/80">
								{members.map((connection) => (
									<ConnectionInfoCard
										key={connection.database_name}
										connection={connection}
										onEdit={onEdit}
										onDelete={onDelete}
										onRefresh={onRefresh}
										refreshPending={refreshPending === connection.database_name}
										onSsoFederationChange={onSsoFederationChange}
										ssoFederationPending={
											ssoFederationPending === connection.database_name
										}
									/>
								))}
							</div>
						)}
					</section>
				);
			})}
		</div>
	);
};
