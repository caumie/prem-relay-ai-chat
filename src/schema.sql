create table if not exists active_users (
    id integer primary key,
    login_name text not null unique,
    password_hash text not null,
    is_admin integer not null default 0,
    suspended_at text,
    created_at text not null,
    updated_at text not null
);
create table if not exists deleted_users (
    id integer primary key,
    login_name text not null,
    deleted_at text not null
);
create table if not exists base_assistants (
    id text primary key,
    name text not null,
    description text not null,
    system_prompt text not null,
    user_prompts_json text not null,
    connection_provider_id text not null,
    model text not null,
    generation_config_json text not null,
    max_history_messages integer not null,
    allow_file_upload integer not null,
    allowed_file_extensions_json text not null,
    deleted_at text,
    created_at text not null,
    updated_at text not null
);
create table if not exists user_assistants (
    id text primary key,
    base_assistant_id text,
    owner_user_id integer not null,
    name text not null,
    description text not null,
    user_prompts_json text not null,
    visibility text not null,
    deleted_at text,
    created_at text not null,
    updated_at text not null,
    foreign key (base_assistant_id) references base_assistants(id) on delete set null,
    foreign key (owner_user_id) references active_users(id) on delete cascade
);
create table if not exists threads (
    id text primary key,
    user_id integer not null,
    title text not null,
    created_at text not null,
    updated_at text not null,
    deleted_at text,
    foreign key (user_id) references active_users(id) on delete cascade
);
create table if not exists messages (
    id integer primary key,
    thread_id text not null,
    role text not null,
    status text not null,
    assistant_id text,
    created_at text not null,
    updated_at text not null,
    foreign key (thread_id) references threads(id) on delete cascade
);
create table if not exists message_kinds (
    id integer primary key,
    message_id integer not null,
    order_index integer not null,
    kind text not null,
    content text not null,
    metadata_json text,
    created_at text not null,
    foreign key (message_id) references messages(id) on delete cascade
);
create table if not exists attachments (
    id text primary key,
    user_id integer not null,
    original_filename text not null,
    stored_path text not null,
    content_type text not null,
    size_bytes integer not null,
    sha256 text not null,
    created_at text not null,
    foreign key (user_id) references active_users(id) on delete cascade
);
create index if not exists active_users_login_idx on active_users(login_name);
create index if not exists active_users_status_idx on active_users(suspended_at, login_name);
create index if not exists threads_user_updated_idx on threads(user_id, updated_at desc);
create index if not exists messages_thread_created_idx on messages(thread_id, created_at asc);
create index if not exists message_kinds_message_order_idx on message_kinds(message_id, order_index asc);
create index if not exists attachments_user_created_idx on attachments(user_id, created_at desc);
create index if not exists base_assistants_active_idx on base_assistants(deleted_at, name);
create index if not exists user_assistants_owner_idx on user_assistants(owner_user_id, name);
create index if not exists user_assistants_base_idx on user_assistants(base_assistant_id, deleted_at);
