-- Skema database Register DHK (PostgreSQL)
-- Dibuat otomatis oleh: DHKRegister.exe --export-schema
-- Aplikasi membuat tabel ini sendiri saat --init-db; berkas ini untuk keperluan DBA/dokumentasi.

CREATE TABLE app_info (
	key VARCHAR(60) NOT NULL, 
	value VARCHAR(255), 
	PRIMARY KEY (key)
);

CREATE TABLE audit_log (
	id SERIAL NOT NULL, 
	ts TIMESTAMP WITHOUT TIME ZONE, 
	user_id INTEGER, 
	username VARCHAR(80), 
	ip VARCHAR(64), 
	user_agent VARCHAR(255), 
	method VARCHAR(10), 
	path VARCHAR(300), 
	category VARCHAR(12), 
	level VARCHAR(8), 
	action VARCHAR(60), 
	menu VARCHAR(80), 
	detail TEXT, 
	mitre_id VARCHAR(16), 
	mitre_tactic VARCHAR(60), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_audit_log_action ON audit_log (action);
CREATE INDEX ix_audit_log_category ON audit_log (category);
CREATE INDEX ix_audit_log_ts ON audit_log (ts);
CREATE INDEX ix_audit_log_username ON audit_log (username);

CREATE TABLE parameter (
	id SERIAL NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	label VARCHAR(150) NOT NULL, 
	description TEXT, 
	sort_order INTEGER, 
	active BOOLEAN, 
	meta JSON, 
	PRIMARY KEY (id), 
	UNIQUE (category, label)
);
CREATE INDEX ix_parameter_category ON parameter (category);

CREATE TABLE register (
	id SERIAL NOT NULL, 
	tanggal_permintaan DATE, 
	unit_kerja VARCHAR(150), 
	pic VARCHAR(150), 
	dokumen_hukum VARCHAR(500), 
	klasifikasi VARCHAR(150), 
	pihak_ketiga VARCHAR(300), 
	tujuan VARCHAR(300), 
	media VARCHAR(150), 
	watermark BOOLEAN, 
	isi_watermark VARCHAR(300), 
	password BOOLEAN, 
	cara_kirim_password VARCHAR(150), 
	data_pribadi BOOLEAN, 
	redaksi BOOLEAN, 
	nda BOOLEAN, 
	tanggal_pengiriman DATE, 
	pic_dhk VARCHAR(150), 
	keterangan TEXT, 
	created_by VARCHAR(80), 
	updated_by VARCHAR(80), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_register_tanggal_permintaan ON register (tanggal_permintaan);

CREATE TABLE role (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	permissions JSON, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE attachment (
	id SERIAL NOT NULL, 
	register_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(register_id) REFERENCES register (id)
);
CREATE INDEX ix_attachment_register_id ON attachment (register_id);

CREATE TABLE "user" (
	id SERIAL NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	full_name VARCHAR(150), 
	email VARCHAR(150), 
	password_hash VARCHAR(255), 
	auth_source VARCHAR(10), 
	role_id INTEGER, 
	active BOOLEAN, 
	failed_login INTEGER, 
	locked_until TIMESTAMP WITHOUT TIME ZONE, 
	last_login TIMESTAMP WITHOUT TIME ZONE, 
	must_change_pw BOOLEAN,
	unit_kerja VARCHAR(150),
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(role_id) REFERENCES role (id)
);
CREATE UNIQUE INDEX ix_user_username ON "user" (username);

CREATE TABLE attachment_version (
	id SERIAL NOT NULL, 
	attachment_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	filename VARCHAR(255), 
	mime VARCHAR(120), 
	size INTEGER, 
	sha256 VARCHAR(64), 
	scan_status VARCHAR(20), 
	scan_detail TEXT, 
	note VARCHAR(250), 
	uploaded_by VARCHAR(80), 
	uploaded_at TIMESTAMP WITHOUT TIME ZONE, 
	content BYTEA, 
	PRIMARY KEY (id), 
	FOREIGN KEY(attachment_id) REFERENCES attachment (id)
);
CREATE INDEX ix_attachment_version_attachment_id ON attachment_version (attachment_id);
