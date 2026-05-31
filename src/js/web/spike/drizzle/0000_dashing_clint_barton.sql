CREATE TABLE `asset_field_values` (
	`tenant_id` text NOT NULL,
	`asset_id` text NOT NULL,
	`field_id` text NOT NULL,
	`value_json` text,
	`hlc` text NOT NULL,
	PRIMARY KEY(`tenant_id`, `asset_id`, `field_id`)
);
--> statement-breakpoint
CREATE TABLE `assets` (
	`tenant_id` text NOT NULL,
	`id` text NOT NULL,
	`type_id` text NOT NULL,
	`name` text,
	`properties` text DEFAULT '{}' NOT NULL,
	`deleted` integer DEFAULT false NOT NULL,
	`row_state_hlc` text NOT NULL,
	PRIMARY KEY(`tenant_id`, `id`)
);
