// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState, useSyncExternalStore } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Placeholders } from '@/assets/images/placeholders';
import { Button } from '@/common/Button';
import { EmptyState } from '@/common/EmptyState';
import { Size, ButtonTheme } from '@/enums/button';
import { ConnectionType } from '@/enums/connection';
import { EmptyStateVariant } from '@/enums/emptyState';
import { ToastVariant } from '@/enums/toast';
import { ConnectionsInfoCardView } from '@/components/connectionsPage/ConnectionsInfoCardView';
import { ConnectionModal } from '@/components/connectionsPage/ConnectionModal';
import { ConfirmModal } from '@/common/modal';
import { Toast } from '@/common/Toast';
import { t } from '@/i18n';
import { Icon, IconName } from '@/common/icons';
import { connectionsApi } from '@/api/connections';
import {
	connectionQueries,
	invalidateConnectionList,
	patchConnectionList,
} from '@/lib/queries/connections';
import type { Connection } from '@/types/connection';

/** There is nothing to subscribe to; the snapshot changes once, at hydration. */
const subscribeToHydration = () => () => {};

export const ConnectionsView = () => {
	const queryClient = useQueryClient();

	// Prefetched by the root layout, so the browser subscribes to a read that
	// is already in flight instead of starting its own after mount.
	const {
		data: connections = [],
		isPending: loading,
		error: loadError,
		refetch,
	} = useQuery(connectionQueries.list());
	const error = loadError?.message ?? null;

	/** Where a write puts what it just changed — the list the page reads from. */
	const patchConnections = (update: Parameters<typeof patchConnectionList>[1]) =>
		patchConnectionList(queryClient, update);

	const [connectionModalOpen, setConnectionModalOpen] = useState(false);
	const [editingConnection, setEditingConnection] = useState<Connection | null>(null);
	const [presetType, setPresetType] = useState<ConnectionType | null>(null);
	const [deletingConnection, setDeletingConnection] = useState<string | null>(null);
	const [deleting, setDeleting] = useState(false);
	const [deleteError, setDeleteError] = useState<string | null>(null);
	const [ssoFederationPending, setSsoFederationPending] = useState<string | null>(null);
	const [ssoError, setSsoError] = useState<string | null>(null);
	const [refreshing, setRefreshing] = useState<string | null>(null);
	const [refreshToast, setRefreshToast] = useState<{
		variant: ToastVariant;
		message: string;
	} | null>(null);

	/**
	 * The prerendered markup always shows the loading shell. Waiting for the
	 * hydration pass before drawing the list keeps that markup and the first
	 * client render identical, so React does not have to throw the tree away
	 * and replay it.
	 */
	const hasMounted = useSyncExternalStore(
		subscribeToHydration,
		() => true,
		() => false,
	);

	const handleCreateConnection = (type: ConnectionType | null = null) => {
		setEditingConnection(null);
		setPresetType(type);
		setConnectionModalOpen(true);
	};

	const handleEditConnection = (connection: Connection) => {
		setEditingConnection(connection);
		setPresetType(null);
		setConnectionModalOpen(true);
	};

	const handleConnectionModalClose = () => {
		setConnectionModalOpen(false);
		setEditingConnection(null);
		setPresetType(null);
	};

	const handleConnectionModalConfirm = () => {
		handleConnectionModalClose();
		void invalidateConnectionList(queryClient);
	};

	const handleSsoFederationChange = async (databaseName: string, enabled: boolean) => {
		setSsoError(null);
		setSsoFederationPending(databaseName);

		// Optimistic update — applied before the write so the checkbox doesn't
		// snap back while it is out.
		await patchConnections((prev) =>
			prev.map((c) =>
				c.database_name === databaseName
					? { ...c, connection: { ...c.connection, sso_federation: enabled } }
					: c,
			),
		);

		const res = await connectionsApi.setSsoFederation(databaseName, enabled);
		setSsoFederationPending(null);

		if (res.error) {
			// Revert optimistic update on failure.
			await patchConnections((prev) =>
				prev.map((c) =>
					c.database_name === databaseName
						? { ...c, connection: { ...c.connection, sso_federation: !enabled } }
						: c,
				),
			);
			setSsoError(res.message ?? t('Failed to update connection.'));
		}
	};

	const handleDeleteRequest = (databaseName: string) => {
		setDeleteError(null);
		setDeletingConnection(databaseName);
	};

	const handleRefresh = async (databaseName: string) => {
		setRefreshing(databaseName);
		setRefreshToast(null);
		const res = await connectionsApi.refresh(databaseName);
		setRefreshing(null);

		if ('error' in res && res.error) {
			setRefreshToast({
				variant: ToastVariant.Error,
				message: res.message ?? t('Failed to refresh the data.'),
			});
			return;
		}
		setRefreshToast({
			variant: ToastVariant.Success,
			message: t('Fetched the latest data for {0}.', { 0: databaseName }),
		});
		await invalidateConnectionList(queryClient);
	};

	const handleDeleteClose = () => {
		if (deleting) return;
		setDeletingConnection(null);
		setDeleteError(null);
	};

	const handleDeleteConfirm = async () => {
		if (deletingConnection == null) return;
		setDeleting(true);
		setDeleteError(null);
		const res = await connectionsApi.delete(deletingConnection);
		setDeleting(false);

		if (res.error) {
			setDeleteError(res.message ?? t('Failed to delete connection.'));
			return;
		}

		await patchConnections((prev) =>
			prev.filter((c) => c.database_name !== deletingConnection),
		);
		setDeletingConnection(null);
	};

	if (!hasMounted || loading) {
		return (
			<div className="flex h-full w-full flex-1 flex-col gap-4 p-6">
				<div className="h-8 w-48 animate-pulse rounded-md bg-zinc-100 dark:bg-zinc-800/70" />
				<ConnectionsInfoCardView connections={[]} loading />
			</div>
		);
	}

	if (error) {
		return (
			<div className="flex h-full w-full flex-1 flex-col items-center justify-center gap-3 px-6">
				<p className="text-sm text-red-600 dark:text-red-400">{error}</p>
				<Button
					theme={ButtonTheme.Secondary}
					size={Size.REGULAR}
					type="button"
					onClick={() => {
						void refetch();
					}}
				>
					{t('Retry')}{' '}
				</Button>
			</div>
		);
	}

	return (
		<div className="flex h-full w-full min-w-0 flex-1 flex-col items-start">
			{connections.length === 0 ? (
				<EmptyState
					variant={EmptyStateVariant.Borderless}
					illustration={<Placeholders.NoConnections />}
					title={t('No Connections Created Yet')}
					description={t(
						'Connect a database, upload an Excel/CSV file, or read rows from a REST API endpoint.',
					)}
					action={{
						label: t('Create New Connection'),
						icon: IconName.Database,
						onClick: () => handleCreateConnection(),
					}}
				/>
			) : (
				<div className="flex w-full flex-col items-start gap-5">
					<div className="flex w-full items-center justify-end gap-2">
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							onClick={() => handleCreateConnection(ConnectionType.API)}
							iconPosition="left"
						>
							<Icon name={IconName.Link} className="h-4 w-4" />
							{t('Connect API')}{' '}
						</Button>
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							onClick={() => handleCreateConnection()}
							iconPosition="left"
							shadow
						>
							<Icon name={IconName.Database} className="h-4 w-4" />
							{t('Create New Connection')}{' '}
						</Button>
					</div>
					<ConnectionsInfoCardView
						connections={connections}
						onEdit={handleEditConnection}
						onDelete={handleDeleteRequest}
						onRefresh={(databaseName) => {
							void handleRefresh(databaseName);
						}}
						refreshPending={refreshing}
						onSsoFederationChange={(databaseName, enabled) => {
							void handleSsoFederationChange(databaseName, enabled);
						}}
						ssoFederationPending={ssoFederationPending}
					/>
				</div>
			)}

			<ConfirmModal
				open={deletingConnection !== null}
				title={t('Remove Connection')}
				message={
					deletingConnection ? (
						<>
							{t('Are you sure you want to remove')}{' '}
							<strong>{deletingConnection}</strong>
							{t(
								'? The connection goes away immediately; its ingested data is cleaned up in the background. This action cannot be undone.',
							)}{' '}
						</>
					) : null
				}
				confirmLabel={t('Remove')}
				onConfirm={handleDeleteConfirm}
				onCancel={handleDeleteClose}
				confirming={deleting}
				error={deleteError}
			/>

			<ConnectionModal
				key={`${connectionModalOpen}:${editingConnection?.database_name ?? ''}:${presetType ?? ''}`}
				open={connectionModalOpen}
				connection={editingConnection}
				initialType={presetType}
				onConfirm={handleConnectionModalConfirm}
				onCancel={handleConnectionModalClose}
			/>

			<Toast
				open={ssoError !== null}
				message={ssoError ?? ''}
				variant={ToastVariant.Error}
				onClose={() => setSsoError(null)}
			/>

			<Toast
				open={refreshToast !== null}
				message={refreshToast?.message ?? ''}
				variant={refreshToast?.variant ?? ToastVariant.Info}
				onClose={() => setRefreshToast(null)}
			/>
		</div>
	);
};
