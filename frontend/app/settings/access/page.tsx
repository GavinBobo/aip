// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { accessApi } from '@/api/access';
import { zonesApi } from '@/api/zones';
import { Button } from '@/common/Button';
import { ConfirmModal } from '@/common/modal';
import { Icon, IconName } from '@/common/icons';
import { t } from '@/i18n';
import { ButtonTheme, Size } from '@/enums/button';
import type { AccessUser, Department } from '@/types/access';
import type { Zone, ZoneGrant, ZonePermission } from '@/types/zones';

type Draft = {
	id: string | null;
	name: string;
	description: string;
	userIds: string[];
};

const emptyDraft: Draft = { id: null, name: '', description: '', userIds: [] };

const messageOf = (error: unknown, fallback: string): string => {
	if (typeof error === 'object' && error && 'message' in error) {
		const message = (error as { message?: string }).message;
		if (message) return message;
	}
	return fallback;
};

export default function DataAccessPage() {
	const [departments, setDepartments] = useState<Department[]>([]);
	const [users, setUsers] = useState<AccessUser[]>([]);
	const [zones, setZones] = useState<Zone[]>([]);
	const [draft, setDraft] = useState<Draft>(emptyDraft);
	const [userDepts, setUserDepts] = useState<Record<string, string[]>>({});
	const [zoneGrants, setZoneGrants] = useState<Record<string, ZoneGrant[]>>({});
	const [loading, setLoading] = useState(true);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [notice, setNotice] = useState<string | null>(null);
	const [pendingDelete, setPendingDelete] = useState<Department | null>(null);
	const [savingUserId, setSavingUserId] = useState<string | null>(null);
	const [savingZoneId, setSavingZoneId] = useState<string | null>(null);

	const accountName = useCallback(
		(id: string) => users.find((user) => user.id === id)?.name || id,
		[users],
	);

	const refresh = useCallback(async () => {
		const [deptResult, userResult, zoneResult] = await Promise.all([
			accessApi.departments(),
			accessApi.users(),
			zonesApi.getAll(),
		]);
		if (deptResult.error || userResult.error || zoneResult.error) {
			setError(
				deptResult.message ??
					userResult.message ??
					zoneResult.message ??
					t('Failed to load data access.'),
			);
		} else {
			setError(null);
		}
		const nextDepartments = deptResult.data ?? [];
		const nextUsers = userResult.data ?? [];
		const nextZones = zoneResult.data ?? [];
		setDepartments(nextDepartments);
		setUsers(nextUsers);
		setZones(nextZones);
		setUserDepts(Object.fromEntries(nextUsers.map((user) => [user.id, user.dept_ids])));
		setZoneGrants(
			Object.fromEntries(
				nextZones.map((zone) => [
					zone.id,
					zone.access?.grants?.length
						? zone.access.grants
						: [
								...(zone.access?.user_ids ?? []).map((id) => ({
									subject_type: 'user' as const,
									subject_id: id,
									permission: 'read' as const,
								})),
								...(zone.access?.dept_ids ?? []).map((id) => ({
									subject_type: 'department' as const,
									subject_id: id,
									permission: 'read' as const,
								})),
							],
				]),
			),
		);
		setLoading(false);
	}, []);

	useEffect(() => {
		// Kick the async load off the effect body: the lint rule (correctly)
		// treats a synchronous setState in an effect as a cascading render.
		const timer = setTimeout(() => {
			void refresh();
		}, 0);
		return () => clearTimeout(timer);
	}, [refresh]);

	const departmentById = useMemo(
		() => new Map(departments.map((department) => [department.id, department])),
		[departments],
	);

	const startEdit = (department: Department) => {
		setDraft({
			id: department.id,
			name: department.name,
			description: department.description,
			userIds: department.user_ids,
		});
		setNotice(null);
		setError(null);
	};

	const saveDepartment = async () => {
		const name = draft.name.trim();
		if (!name) {
			setError(t('Department name is required.'));
			return;
		}
		setSaving(true);
		setError(null);
		const input = {
			name,
			description: draft.description.trim() || null,
			user_ids: draft.userIds,
		};
		const result = draft.id
			? await accessApi.updateDepartment(draft.id, input)
			: await accessApi.createDepartment(input);
		setSaving(false);
		if (result.error) {
			setError(messageOf(result.error, t('Failed to save the department.')));
			return;
		}
		setDraft(emptyDraft);
		setNotice(t('Department saved.'));
		await refresh();
	};

	const deleteDepartment = async () => {
		if (!pendingDelete) return;
		setSaving(true);
		const result = await accessApi.deleteDepartment(pendingDelete.id);
		setSaving(false);
		setPendingDelete(null);
		if (result.error) {
			setError(messageOf(result.error, t('Failed to delete the department.')));
			return;
		}
		setNotice(t('Department deleted.'));
		await refresh();
	};

	const saveUserDepartments = async (userId: string) => {
		setSavingUserId(userId);
		setError(null);
		const result = await accessApi.setUserDepartments(userId, userDepts[userId] ?? []);
		setSavingUserId(null);
		if (result.error) {
			setError(messageOf(result.error, t('Failed to update the user departments.')));
			return;
		}
		setNotice(t('User departments saved.'));
	};

	const saveZoneGrants = async (zoneId: string) => {
		setSavingZoneId(zoneId);
		setError(null);
		const result = await zonesApi.setAccess(zoneId, {
			grants: zoneGrants[zoneId] ?? [],
		});
		setSavingZoneId(null);
		if (result.error) {
			setError(messageOf(result.error, t('Failed to update the zone access.')));
			return;
		}
		setNotice(t('Zone access saved.'));
		await refresh();
	};

	const updateUserDepts = (userId: string, selected: string[]) => {
		setUserDepts((current) => ({ ...current, [userId]: selected }));
	};

	const updateZoneGrantSubjects = (
		zoneId: string,
		subjectType: ZoneGrant['subject_type'],
		selectedIds: string[],
	) => {
		setZoneGrants((current) => {
			const existing = current[zoneId] ?? [];
			const byId = new Map(
				existing
					.filter((grant) => grant.subject_type === subjectType)
					.map((grant) => [grant.subject_id, grant]),
			);
			const next = existing.filter((grant) => grant.subject_type !== subjectType);
			selectedIds.forEach((subjectId) => {
				next.push(
					byId.get(subjectId) ?? {
						subject_type: subjectType,
						subject_id: subjectId,
						permission: 'read' as const,
					},
				);
			});
			return { ...current, [zoneId]: next };
		});
	};

	const setZoneGrantPermission = (
		zoneId: string,
		subjectType: ZoneGrant['subject_type'],
		subjectId: string,
		permission: ZonePermission,
	) => {
		setZoneGrants((current) => ({
			...current,
			[zoneId]: (current[zoneId] ?? []).map((grant) =>
				grant.subject_type === subjectType && grant.subject_id === subjectId
					? { ...grant, permission }
					: grant,
			),
		}));
	};

	return (
		<main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,rgba(255,255,255,1)_0%,rgba(250,250,250,0.6)_100%)] px-7 py-6 sm:px-10 sm:py-7 dark:bg-[linear-gradient(180deg,rgba(9,9,11,1)_0%,rgba(24,24,27,0.5)_100%)]">
			<div className="w-full space-y-8">
				<header>
					<h1 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Data Access')}
					</h1>
					<p className="mt-1 max-w-3xl text-sm text-secondary dark:text-zinc-400">
						{t(
							'Grant Zones to individual users or departments. A user can see the union of their direct grants and every department they belong to. Admins always see all data.',
						)}
					</p>
				</header>

				{error ? (
					<div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
						{error}
					</div>
				) : null}
				{notice ? (
					<div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-200">
						{notice}
					</div>
				) : null}

				<section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-950/50">
					<div className="flex flex-wrap items-start justify-between gap-3">
						<div>
							<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
								{t('Departments')}
							</h2>
							<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
								{t(
									'Department membership acts as an inheritance rule for Zone grants.',
								)}
							</p>
						</div>
						{draft.id ? (
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.SMALL}
								type="button"
								onClick={() => setDraft(emptyDraft)}
							>
								{t('Cancel edit')}
							</Button>
						) : null}
					</div>

					<div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto]">
						<input
							value={draft.name}
							onChange={(event) => setDraft({ ...draft, name: event.target.value })}
							placeholder={t('Department name')}
							className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						/>
						<input
							value={draft.description}
							onChange={(event) =>
								setDraft({ ...draft, description: event.target.value })
							}
							placeholder={t('Description (optional)')}
							className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						/>
						<Button
							theme={ButtonTheme.Primary}
							size={Size.SMALL}
							type="button"
							loading={saving}
							onClick={() => void saveDepartment()}
						>
							{draft.id ? t('Save department') : t('Create department')}
						</Button>
					</div>
					<div className="mt-3">
						<span className="mb-1 block text-xs font-medium text-secondary dark:text-zinc-400">
							{t('Members')}
						</span>
						<select
							multiple
							value={draft.userIds}
							onChange={(event) =>
								setDraft({
									...draft,
									userIds: Array.from(
										event.target.selectedOptions,
										(option) => option.value,
									),
								})
							}
							className="h-28 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						>
							{users.map((user) => (
								<option key={user.id} value={user.id}>
									{user.name || user.email || user.id}
								</option>
							))}
						</select>
					</div>

					<div className="mt-4 overflow-x-auto">
						<table className="w-full text-sm">
							<thead className="text-left text-xs uppercase tracking-wide text-secondary dark:text-zinc-500">
								<tr>
									<th className="py-2 pr-3">{t('Name')}</th>
									<th className="py-2 pr-3">{t('Members')}</th>
									<th className="py-2 pr-3">{t('Description')}</th>
									<th className="py-2 text-right">{t('Actions')}</th>
								</tr>
							</thead>
							<tbody>
								{departments.map((department) => (
									<tr
										key={department.id}
										className="border-t border-zinc-200 dark:border-zinc-800"
									>
										<td className="py-2 pr-3 font-medium">{department.name}</td>
										<td className="py-2 pr-3 text-secondary dark:text-zinc-400">
											{department.users.length
												? department.users
														.map(
															(member) =>
																member.name ||
																member.email ||
																member.id,
														)
														.join(', ')
												: t('No members')}
										</td>
										<td className="py-2 pr-3 text-secondary dark:text-zinc-400">
											{department.description || '—'}
										</td>
										<td className="py-2 text-right">
											<Button
												theme={ButtonTheme.IconNeutral}
												size={Size.SMALL}
												iconOnly
												type="button"
												onClick={() => startEdit(department)}
												aria-label={t('Edit {0}', { 0: department.name })}
											>
												<Icon name={IconName.Pencil} className="h-4 w-4" />
											</Button>
											<span className="ml-1 inline-flex">
												<Button
													theme={ButtonTheme.IconNeutral}
													size={Size.SMALL}
													iconOnly
													type="button"
													onClick={() => setPendingDelete(department)}
													aria-label={t('Delete {0}', {
														0: department.name,
													})}
												>
													<Icon
														name={IconName.Trash}
														className="h-4 w-4"
													/>
												</Button>
											</span>
										</td>
									</tr>
								))}
							</tbody>
						</table>
						{!loading && departments.length === 0 ? (
							<p className="py-4 text-sm text-secondary dark:text-zinc-400">
								{t('No departments yet.')}
							</p>
						) : null}
					</div>
				</section>

				<section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-950/50">
					<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
						{t('User departments')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{t('A user may belong to more than one department; access is additive.')}
					</p>
					<div className="mt-4 overflow-x-auto">
						<table className="w-full text-sm">
							<thead className="text-left text-xs uppercase tracking-wide text-secondary dark:text-zinc-500">
								<tr>
									<th className="py-2 pr-3">{t('User')}</th>
									<th className="py-2 pr-3">{t('Departments')}</th>
									<th className="py-2 text-right">{t('Actions')}</th>
								</tr>
							</thead>
							<tbody>
								{users.map((user) => (
									<tr
										key={user.id}
										className="border-t border-zinc-200 dark:border-zinc-800"
									>
										<td className="py-2 pr-3">
											<div className="font-medium">{user.name || '—'}</div>
											<div className="text-xs text-secondary">
												{user.email}
											</div>
										</td>
										<td className="py-2 pr-3">
											<select
												multiple
												value={userDepts[user.id] ?? []}
												onChange={(event) =>
													updateUserDepts(
														user.id,
														Array.from(
															event.target.selectedOptions,
															(option) => option.value,
														),
													)
												}
												className="h-24 min-w-56 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
											>
												{departments.map((department) => (
													<option
														key={department.id}
														value={department.id}
													>
														{department.name}
													</option>
												))}
											</select>
										</td>
										<td className="py-2 text-right align-top">
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												type="button"
												loading={savingUserId === user.id}
												onClick={() => void saveUserDepartments(user.id)}
											>
												{t('Save')}
											</Button>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</section>

				<section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-950/50">
					<h2 className="text-sm font-semibold text-heading dark:text-zinc-100">
						{t('Zone grants')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{t(
							'Choose which users and departments can use each Zone. A disabled Zone grants nothing.',
						)}
					</p>
					<div className="mt-4 space-y-4">
						{zones.map((zone) => {
							const grants = zoneGrants[zone.id] ?? [];
							const userIds = grants
								.filter((grant) => grant.subject_type === 'user')
								.map((grant) => grant.subject_id);
							const deptIds = grants
								.filter((grant) => grant.subject_type === 'department')
								.map((grant) => grant.subject_id);
							return (
								<div
									key={zone.id}
									className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-700"
								>
									<div className="flex flex-wrap items-center justify-between gap-3">
										<div>
											<div className="font-medium text-heading dark:text-zinc-100">
												{zone.name}
												{!zone.enabled ? (
													<span className="ml-2 rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] uppercase dark:bg-zinc-700">
														{t('Disabled')}
													</span>
												) : null}
											</div>
											<div className="mt-1 text-xs text-secondary dark:text-zinc-400">
												{grants.length} {t('grants')}
											</div>
										</div>
										<Button
											theme={ButtonTheme.Secondary}
											size={Size.SMALL}
											type="button"
											loading={savingZoneId === zone.id}
											onClick={() => void saveZoneGrants(zone.id)}
										>
											{t('Save grants')}
										</Button>
									</div>
									<div className="mt-3 grid gap-3 md:grid-cols-2">
										<label className="text-xs font-medium text-secondary dark:text-zinc-400">
											{t('Users')}
											<select
												multiple
												value={userIds}
												onChange={(event) =>
													updateZoneGrantSubjects(
														zone.id,
														'user',
														Array.from(
															event.target.selectedOptions,
															(option) => option.value,
														),
													)
												}
												className="mt-1 h-24 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
											>
												{users.map((user) => (
													<option key={user.id} value={user.id}>
														{accountName(user.id)}
													</option>
												))}
											</select>
										</label>
										<label className="text-xs font-medium text-secondary dark:text-zinc-400">
											{t('Departments')}
											<select
												multiple
												value={deptIds}
												onChange={(event) =>
													updateZoneGrantSubjects(
														zone.id,
														'department',
														Array.from(
															event.target.selectedOptions,
															(option) => option.value,
														),
													)
												}
												className="mt-1 h-24 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
											>
												{departments.map((department) => (
													<option
														key={department.id}
														value={department.id}
													>
														{department.name}
													</option>
												))}
											</select>
										</label>
									</div>
									{grants.length ? (
										<div className="mt-3 space-y-2">
											{grants.map((grant) => (
												<div
													key={`${grant.subject_type}:${grant.subject_id}`}
													className="flex flex-wrap items-center justify-between gap-2 text-xs"
												>
													<span className="text-body dark:text-zinc-300">
														{grant.subject_type === 'user'
															? accountName(grant.subject_id)
															: (departmentById.get(grant.subject_id)
																	?.name ?? grant.subject_id)}
													</span>
													<select
														value={grant.permission}
														onChange={(event) =>
															setZoneGrantPermission(
																zone.id,
																grant.subject_type,
																grant.subject_id,
																event.target
																	.value as ZonePermission,
															)
														}
														className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
													>
														<option value="read">{t('Read')}</option>
														<option value="edit">{t('Edit')}</option>
														<option value="manage">
															{t('Manage')}
														</option>
													</select>
												</div>
											))}
										</div>
									) : null}
									{deptIds.length ? (
										<p className="mt-2 text-xs text-secondary dark:text-zinc-400">
											{t('Inherited by')}:{' '}
											{deptIds
												.map((id) => departmentById.get(id)?.name ?? id)
												.join(', ')}
										</p>
									) : null}
								</div>
							);
						})}
					</div>
				</section>
			</div>
			<ConfirmModal
				open={pendingDelete !== null}
				title={t('Delete Department')}
				message={t(
					'Deleting this department removes its memberships and Zone grants. Continue?',
				)}
				onConfirm={() => void deleteDepartment()}
				onCancel={() => setPendingDelete(null)}
				confirming={saving}
			/>
		</main>
	);
}
