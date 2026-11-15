// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { IconName } from '@/common/icons';
import { ConnectionType, connectionDisplayName } from '@/enums/connection';

export type ConnectionKind = {
	key: ConnectionType;
	label: string;
	icon: IconName;
};

const CONNECTION_ICONS: Partial<Record<ConnectionType, IconName>> = {
	[ConnectionType.FILE]: IconName.Spreadsheet,
	[ConnectionType.API]: IconName.Link,
};

export const connectionKind = (type: ConnectionType): ConnectionKind => ({
	key: type,
	label: connectionDisplayName[type],
	icon: CONNECTION_ICONS[type] ?? IconName.Database,
});

/** Files and APIs lead; database engines follow alphabetically. */
export const connectionKindRank = (type: ConnectionType): number => {
	if (type === ConnectionType.FILE) return 0;
	if (type === ConnectionType.API) return 1;
	return 2;
};
