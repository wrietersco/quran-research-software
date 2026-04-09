"""Thin wrappers around OpenAI Files and Vector Stores APIs for the admin UI."""

from src.openai_platform.resources import (
    OpenAIAdminError,
    attach_file_to_vector_store,
    create_vector_store,
    delete_file,
    delete_vector_store,
    delete_vector_store_file,
    list_files,
    list_vector_store_files,
    list_vector_stores,
    make_openai_client,
    upload_file_to_openai,
)

__all__ = [
    "OpenAIAdminError",
    "attach_file_to_vector_store",
    "create_vector_store",
    "delete_file",
    "delete_vector_store",
    "delete_vector_store_file",
    "list_files",
    "list_vector_store_files",
    "list_vector_stores",
    "make_openai_client",
    "upload_file_to_openai",
]
