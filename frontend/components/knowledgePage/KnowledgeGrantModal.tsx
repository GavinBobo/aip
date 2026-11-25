// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';

import { accessApi } from '@/api/access';
import { knowledgeApi, type KnowledgeGrantAudit } from '@/api/knowledge';
import { Button } from '@/common/Button';
import { formatDateTime } from '@/common/date';
import { Icon, IconName } from '@/common/icons';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { AccessUser, Department } from '@/types/access';

export const KnowledgeGrantModal = ({
	networkId,
	onClose,
}: {
	networkId: string;
	onClose: () => void;
}) => {
	const [users, setUsers] = useState<AccessUser[]>([]);
	const [departments, setDepartments] = useState<Department[]>([]);
	const [userIds, setUserIds] = useState<string[]>([]);
	const [deptIds, setDeptIds] = useState<string[]>([]);
	const [audits, setAudits] = useState<KnowledgeGrantAudit[]>([]);
	const [expiry, setExpiry] = useState('');
	const [userPermissions, setUserPermissions] = useState<
		Record<string, 'read' | 'edit' | 'manage'>
	>({});
	const [deptPermissions, setDeptPermissions] = useState<
		Record<string, 'read' | 'edit' | 'manage'>
	>({});
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		Promise.all([
			accessApi.users(),
			accessApi.departments(),
			knowledgeApi.getGrants(networkId),
			knowledgeApi.listGrantAudit(networkId),
		]).then(([userResponse, deptResponse, grantResponse, auditResponse]) => {
			if (cancelled) return;
			setLoading(false);
			if (
				userResponse.error ||
				!userResponse.data ||
				deptResponse.error ||
				!deptResponse.data
			) {
				setError(
					userResponse.message ??
						deptResponse.message ??
						t('Failed to load access subjects.'),
				);
				return;
			}
			setUsers(userResponse.data);
			setDepartments(deptResponse.data);
			if (!grantResponse.error && grantResponse.data) {
				setUserIds(grantResponse.data.user_ids);
				setDeptIds(grantResponse.data.dept_ids);
				setUserPermissions(
					Object.fromEntries(
						grantResponse.data.grants
							.filter((grant) => grant.user_id)
							.map((grant) => [
								String(grant.user_id),
								(grant.permission as 'read' | 'edit' | 'manage') || 'read',
							]),
					),
				);
				setDeptPermissions(
					Object.fromEntries(
						grantResponse.data.grants
							.filter((grant) => grant.dept_id)
							.map((grant) => [
								String(grant.dept_id),
								(grant.permission as 'read' | 'edit' | 'manage') || 'read',
							]),
					),
				);
				const firstExpiry = grantResponse.data.grants.find(
					(grant) => grant.expires_at,
				)?.expires_at;
				if (firstExpiry) {
					setExpiry(new Date(firstExpiry).toISOString().slice(0, 16));
				}
			}
			if (!auditResponse.error && auditResponse.data) {
				setAudits(auditResponse.data);
			}
		});
		return () => {
			cancelled = true;
		};
	}, [networkId]);

	const toggle = (values: string[], set: (next: string[]) => void, id: string) => {
		set(values.includes(id) ? values.filter((item) => item !== id) : [...values, id]);
	};

	const save = async () => {
		setSaving(true);
		setError(null);
		const response = await knowledgeApi.replaceGrants(networkId, {
			grants: [
				...userIds.map((userId) => ({
					subject_type: 'user' as const,
					subject_id: userId,
					permission: userPermissions[userId] ?? 'read',
					expires_at: expiry ? new Date(expiry).toISOString() : null,
				})),
				...deptIds.map((deptId) => ({
					subject_type: 'department' as const,
					subject_id: deptId,
					permission: deptPermissions[deptId] ?? 'read',
					expires_at: expiry ? new Date(expiry).toISOString() : null,
				})),
			],
		});
		setSaving(false);
		if (response.error) {
			setError(response.message ?? t('Failed to save network access.'));
			return;
		}
		onClose();
	};

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
			role="dialog"
			aria-modal="true"
			aria-label={t('Knowledge network access')}
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
				<div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
					<div>
						<h2 className="text-lg font-semibold text-heading dark:text-zinc-100">
							{t('Knowledge network access')}
						</h2>
						<p className="mt-1 text-sm text-secondary">
							{t(
								'Explicit grants override zone visibility. Leave empty to use zone visibility.',
							)}
						</p>
					</div>
					<Button
						theme={ButtonTheme.IconNeutral}
						size={Size.SMALL}
						iconOnly
						onClick={onClose}
						aria-label={t('Close')}
					>
						<Icon name={IconName.Close} className="h-4 w-4" />
					</Button>
				</div>
				{loading ? (
					<div className="flex h-48 items-center justify-center">
						<Spinner />
					</div>
				) : (
					<div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto px-6 py-4 md:grid-cols-2">
						<section>
							<h3 className="text-xs font-semibold tracking-wide text-secondary uppercase">
								{t('Users')}
							</h3>
							<div className="mt-2 space-y-1">
								{users.map((user) => (
									<div
										key={user.id}
										className="flex items-center gap-2 text-xs text-body"
									>
										<input
											type="checkbox"
											checked={userIds.includes(user.id)}
											onChange={() => toggle(userIds, setUserIds, user.id)}
										/>
										<span className="min-w-0 flex-1 truncate">
											{user.name} · {user.email}
										</span>
										<select
											className="h-6 rounded border border-zinc-300 bg-white px-1 text-[10px] dark:border-zinc-600 dark:bg-zinc-900"
											value={userPermissions[user.id] ?? 'read'}
											disabled={!userIds.includes(user.id)}
											onChange={(event) =>
												setUserPermissions((current) => ({
													...current,
													[user.id]: event.target.value as
														| 'read'
														| 'edit'
														| 'manage',
												}))
											}
										>
											<option value="read">{t('Read')}</option>
											<option value="edit">{t('Edit')}</option>
											<option value="manage">{t('Manage')}</option>
										</select>
									</div>
								))}
							</div>
						</section>
						<section>
							<h3 className="text-xs font-semibold tracking-wide text-secondary uppercase">
								{t('Departments')}
							</h3>
							<div className="mt-2 space-y-1">
								{departments.map((department) => (
									<div
										key={department.id}
										className="flex items-center gap-2 text-xs text-body"
									>
										<input
											type="checkbox"
											checked={deptIds.includes(department.id)}
											onChange={() =>
												toggle(deptIds, setDeptIds, department.id)
											}
										/>
										<span className="min-w-0 flex-1 truncate">
											{department.name}
										</span>
										<select
											className="h-6 rounded border border-zinc-300 bg-white px-1 text-[10px] dark:border-zinc-600 dark:bg-zinc-900"
											value={deptPermissions[department.id] ?? 'read'}
											disabled={!deptIds.includes(department.id)}
											onChange={(event) =>
												setDeptPermissions((current) => ({
													...current,
													[department.id]: event.target.value as
														| 'read'
														| 'edit'
														| 'manage',
												}))
											}
										>
											<option value="read">{t('Read')}</option>
											<option value="edit">{t('Edit')}</option>
											<option value="manage">{t('Manage')}</option>
										</select>
									</div>
								))}
							</div>
						</section>
						<section className="md:col-span-2">
							<h3 className="text-xs font-semibold tracking-wide text-secondary uppercase">
								{t('Grant expiry (optional)')}
							</h3>
							<input
								type="datetime-local"
								className="mt-1 h-8 rounded border border-zinc-300 bg-white px-2 text-xs dark:border-zinc-600 dark:bg-zinc-900"
								value={expiry}
								onChange={(event) => setExpiry(event.target.value)}
							/>
						</section>
						<section className="md:col-span-2">
							<h3 className="text-xs font-semibold tracking-wide text-secondary uppercase">
								{t('Recent access changes')}
							</h3>
							<div className="mt-2 space-y-1">
								{audits.length === 0 && (
									<p className="text-xs text-secondary">
										{t('No access changes yet.')}
									</p>
								)}
								{audits.slice(0, 5).map((audit) => (
									<div
										key={audit.id}
										className="rounded border border-zinc-200 px-2 py-1 text-[11px] text-secondary dark:border-zinc-700"
									>
										{audit.created ? formatDateTime(audit.created) : '—'}
										{' · '}
										{audit.actor_user_id || t('Unknown user')}
										{' · '}
										{t('{count} grants', { count: audit.after.length })}
									</div>
								))}
							</div>
						</section>
					</div>
				)}
				{error && <p className="px-6 pb-2 text-sm text-red-600">{error}</p>}
				<div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
					<Button theme={ButtonTheme.Secondary} onClick={onClose}>
						{t('Cancel')}
					</Button>
					<Button loading={saving} onClick={save}>
						{t('Save access')}
					</Button>
				</div>
			</div>
		</div>
	);
};
