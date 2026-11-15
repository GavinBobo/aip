// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { OptionCard } from '@/components/connectionsPage/steps/OptionCard';
import { Icon, IconName } from '@/common/icons';
import { ConnectionType, connectionDisplayName } from '@/enums/connection';
import { t } from '@/i18n';

export type ConnectionTypeStepProps = {
	onSelect: (type: ConnectionType) => void;
};

/** The two non-warehouse sources are the least discoverable, so they lead. */
const CONNECTOR_HINTS: Partial<Record<ConnectionType, string>> = {
	[ConnectionType.API]: 'Read rows from a JSON endpoint',
	[ConnectionType.FILE]: 'Upload an Excel or CSV file',
};

const CONNECTOR_TYPES = Object.values(ConnectionType).sort((a, b) => {
	const rank = (type: ConnectionType): number =>
		type === ConnectionType.API ? 0 : type === ConnectionType.FILE ? 1 : 2;
	return rank(a) - rank(b) || connectionDisplayName[a].localeCompare(connectionDisplayName[b]);
});

const CONNECTOR_ICONS: Partial<Record<ConnectionType, IconName>> = {
	[ConnectionType.API]: IconName.Link,
	[ConnectionType.FILE]: IconName.Upload,
};

export const ConnectionTypeStep = ({ onSelect }: ConnectionTypeStepProps) => (
	<div className="flex flex-col gap-3 p-2">
		<div className="grid grid-cols-2 gap-3">
			{CONNECTOR_TYPES.map((type) => (
				<OptionCard key={type} onClick={() => onSelect(type)}>
					<Icon
						name={CONNECTOR_ICONS[type] ?? IconName.Database}
						className="h-8 w-8 text-body dark:text-zinc-300"
					/>
					<span className="text-sm font-medium text-heading dark:text-zinc-100">
						{connectionDisplayName[type]}
					</span>
					{CONNECTOR_HINTS[type] != null && (
						<span className="text-center text-xs text-secondary dark:text-zinc-400">
							{t(CONNECTOR_HINTS[type])}
						</span>
					)}
				</OptionCard>
			))}
		</div>
	</div>
);
