from __future__ import annotations

from dataclasses import dataclass

from orchestrator.domain.entities import SeoFlowStep
from orchestrator.domain.indexing import INDEXING_CAPABILITY


@dataclass(frozen=True, slots=True)
class StepDefinition:
    step_name: SeoFlowStep
    default_capability: str | None
    depends_on: tuple[SeoFlowStep, ...] = ()
    manual_gate: bool = False


SEO_MAIN_SUPPORTED_STAGES = frozenset(
    {
        SeoFlowStep.SEO_AUDIT,
        SeoFlowStep.WORDPRESS_PUBLISH,
    }
)


SEO_STEP_DEFINITIONS: dict[SeoFlowStep, StepDefinition] = {
    SeoFlowStep.WORDPRESS_PAGE_SETUP: StepDefinition(
        step_name=SeoFlowStep.WORDPRESS_PAGE_SETUP,
        default_capability="wordpress.page_upsert",
    ),
    SeoFlowStep.CONTEXT_BUILDING: StepDefinition(
        step_name=SeoFlowStep.CONTEXT_BUILDING,
        default_capability="seo.main",
    ),
    SeoFlowStep.WORDPRESS_EXTRACTION: StepDefinition(
        step_name=SeoFlowStep.WORDPRESS_EXTRACTION,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.CONTEXT_BUILDING,),
    ),
    SeoFlowStep.COMPETITOR_ANALYSIS: StepDefinition(
        step_name=SeoFlowStep.COMPETITOR_ANALYSIS,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.CONTEXT_BUILDING,),
    ),
    SeoFlowStep.SEO_AUDIT: StepDefinition(
        step_name=SeoFlowStep.SEO_AUDIT,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.WORDPRESS_PAGE_SETUP,),
    ),
    SeoFlowStep.WORK_PLAN: StepDefinition(
        step_name=SeoFlowStep.WORK_PLAN,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.SEO_AUDIT,),
    ),
    SeoFlowStep.SERVICE_IMAGES: StepDefinition(
        step_name=SeoFlowStep.SERVICE_IMAGES,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.WORK_PLAN,),
    ),
    SeoFlowStep.MAIN_PAGE_FIX: StepDefinition(
        step_name=SeoFlowStep.MAIN_PAGE_FIX,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.SERVICE_IMAGES,),
    ),
    SeoFlowStep.SUPPORT_POSTS: StepDefinition(
        step_name=SeoFlowStep.SUPPORT_POSTS,
        default_capability="posts.create",
        depends_on=(SeoFlowStep.SEO_AUDIT,),
    ),
    SeoFlowStep.VIDEO_REQUEST: StepDefinition(
        step_name=SeoFlowStep.VIDEO_REQUEST,
        default_capability="video.create",
        depends_on=(SeoFlowStep.SEO_AUDIT,),
    ),
    SeoFlowStep.EXTERNAL_ASSETS_RECEIVED: StepDefinition(
        step_name=SeoFlowStep.EXTERNAL_ASSETS_RECEIVED,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.SUPPORT_POSTS, SeoFlowStep.VIDEO_REQUEST),
    ),
    SeoFlowStep.AUTO_REVIEW: StepDefinition(
        step_name=SeoFlowStep.AUTO_REVIEW,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.MAIN_PAGE_FIX, SeoFlowStep.EXTERNAL_ASSETS_RECEIVED),
    ),
    SeoFlowStep.APPROVAL: StepDefinition(
        step_name=SeoFlowStep.APPROVAL,
        default_capability=None,
        depends_on=(SeoFlowStep.AUTO_REVIEW,),
        manual_gate=True,
    ),
    SeoFlowStep.WORDPRESS_PUBLISH: StepDefinition(
        step_name=SeoFlowStep.WORDPRESS_PUBLISH,
        default_capability="seo.main",
        depends_on=(
            SeoFlowStep.SEO_AUDIT,
            SeoFlowStep.SUPPORT_POSTS,
            SeoFlowStep.VIDEO_REQUEST,
        ),
    ),
    SeoFlowStep.POST_PUBLISH_CHECK: StepDefinition(
        step_name=SeoFlowStep.POST_PUBLISH_CHECK,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.WORDPRESS_PUBLISH,),
    ),
    SeoFlowStep.PAGESPEED: StepDefinition(
        step_name=SeoFlowStep.PAGESPEED,
        default_capability="pagespeed.check",
        depends_on=(SeoFlowStep.WORDPRESS_PUBLISH,),
    ),
    SeoFlowStep.INDEXING: StepDefinition(
        step_name=SeoFlowStep.INDEXING,
        default_capability=INDEXING_CAPABILITY,
        depends_on=(SeoFlowStep.PAGESPEED,),
    ),
    SeoFlowStep.FINAL_REPORT: StepDefinition(
        step_name=SeoFlowStep.FINAL_REPORT,
        default_capability="seo.main",
        depends_on=(SeoFlowStep.INDEXING,),
    ),
}


def capability_for_step(step_name: SeoFlowStep, principal_capability: str) -> str | None:
    definition = SEO_STEP_DEFINITIONS[step_name]
    if definition.default_capability == "seo.main":
        return principal_capability
    return definition.default_capability
